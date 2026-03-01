"""
Bot core: scheduler, state machine, signal-to-order execution, reconciliation.

States: IDLE -> PENDING_ENTRY -> OPEN -> CLOSING -> IDLE
                                      -> ERROR_PAUSED
"""

import logging
import math
import time
from datetime import datetime, timezone
from typing import Optional

from config.settings import Config
from data.market_data import fetch_candles, build_htf_candles
from execution.base import ExchangeAdapter, OrderStatusInfo, PositionInfo
from execution.delta_client import DeltaClient
from execution.coinswitch_client import CoinSwitchClient
from strategy.bias_engine import compute_bias
from strategy.entry_engine import build_signal, Signal
from strategy.risk_engine import compute_sizing
from storage.repository import Repository
from bot.alerts import TelegramBot

logger = logging.getLogger(__name__)


class BotState:
    IDLE = "IDLE"
    PENDING_ENTRY = "PENDING_ENTRY"
    OPEN = "OPEN"
    CLOSING = "CLOSING"
    ERROR_PAUSED = "ERROR_PAUSED"


class TradingBot:

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.state = BotState.IDLE
        self.running = False
        self.paused = False

        self.repo = Repository(cfg.sqlite_path)
        self.tg = TelegramBot(cfg.telegram_bot_token, cfg.telegram_chat_id)
        self.exchange: ExchangeAdapter = self._build_exchange()

        # Runtime position (loaded from DB on startup)
        self._open_trade_id: Optional[int] = None
        self._position: Optional[dict] = None  # local copy of open trade row
        self._original_sl: Optional[float] = None  # for 1R breakeven calc

        self._register_commands()

    # --------------------------------------------------------------- setup

    def _build_exchange(self) -> ExchangeAdapter:
        if self.cfg.exchange == "delta_demo":
            return DeltaClient(self.cfg)
        return CoinSwitchClient(self.cfg)

    def _register_commands(self):
        self.tg.register_command("start", self._cmd_start)
        self.tg.register_command("stop", self._cmd_stop)
        self.tg.register_command("status", self._cmd_status)
        self.tg.register_command("trades", self._cmd_trades)
        self.tg.register_command("kill", self._cmd_kill)
        self.tg.register_command("shutdown", self._cmd_shutdown)
        self.tg.register_command("ltf5m", self._cmd_ltf5m)
        self.tg.register_command("ltf15m", self._cmd_ltf15m)
        self.tg.register_command("demo", self._cmd_demo)
        self.tg.register_command("live", self._cmd_live)

    # --------------------------------------------------------------- startup

    def start(self):
        """Main entry point. Sets leverage, recovers state, runs scheduler."""
        logger.info(f"Bot starting: profile={self.cfg.profile} exchange={self.cfg.exchange}")

        # Set leverage on exchange
        ok = self.exchange.set_leverage(self.cfg.symbol, self.cfg.leverage)
        if not ok:
            logger.error("Failed to set leverage on exchange. Aborting.")
            raise RuntimeError("Leverage setup failed")

        # Recover open trade from DB
        open_trade = self.repo.get_open_trade()
        if open_trade:
            logger.info(f"Recovering open trade id={open_trade['id']}")
            self._open_trade_id = open_trade["id"]
            self._position = open_trade
            self.state = BotState.OPEN

        self.running = True
        self.tg.send(
            f"🚀 <b>Bot started</b>\n"
            f"Profile: <code>{self.cfg.profile}</code>\n"
            f"Exchange: <code>{self.cfg.exchange}</code>\n"
            f"Symbol: <code>{self.cfg.symbol}</code>"
        )
        self._run_loop()

    # --------------------------------------------------------------- scheduler

    def _run_loop(self):
        while self.running:
            # Poll Telegram commands
            self.tg.poll_commands()

            if self.paused:
                time.sleep(5)
                continue

            now_utc = datetime.now(timezone.utc)
            next_candle = self._seconds_until_next_candle(now_utc)

            if next_candle > 0:
                # Sleep in small increments to stay responsive to Telegram commands
                sleep_step = min(5, next_candle)
                time.sleep(sleep_step)
                continue

            # It's candle close time — wait buffer then run cycle
            buffer = self.cfg.candle_close_buffer_seconds
            logger.debug(f"Candle boundary reached. Waiting {buffer}s buffer...")
            time.sleep(buffer)

            try:
                self._run_cycle()
            except Exception as e:
                logger.exception(f"Cycle error: {e}")
                self.repo.log_event("ERROR", "cycle_error", str(e))
                self.tg.send_error_alert(f"Cycle error: {e}")

    def _seconds_until_next_candle(self, now_utc: datetime) -> float:
        """Compute seconds until next candle boundary."""
        ts = now_utc.timestamp()
        interval = self.cfg.cycle_seconds
        remainder = ts % interval
        if remainder < 1:
            return 0
        return interval - remainder

    # --------------------------------------------------------------- cycle

    def _run_cycle(self):
        now_utc = datetime.now(timezone.utc)
        logger.info(f"Cycle at {now_utc.strftime('%Y-%m-%d %H:%M:%S')} UTC | state={self.state}")

        # Always reconcile first
        if self.state == BotState.OPEN:
            self._reconcile()
            if self.state != BotState.OPEN:
                return  # position was closed, skip signal logic
            # Manage trailing SL while position is open
            if self.cfg.trailing_sl_enabled:
                self._manage_trailing_sl()
                if self.state != BotState.OPEN:
                    return

        if self.state in (BotState.ERROR_PAUSED, BotState.PENDING_ENTRY, BotState.CLOSING):
            return

        if self.state == BotState.IDLE:
            self._signal_and_enter(now_utc)

    # --------------------------------------------------------------- reconciliation

    def _reconcile(self):
        """Query exchange. If flat while local=OPEN, mark closed with real fill data."""
        pos = self.exchange.get_position(self.cfg.symbol)

        if pos is None:
            logger.warning("Reconcile: get_position returned None (API error). Skipping reconciliation.")
            self.repo.log_event("WARNING", "reconcile_skip", "get_position API error, skipping reconcile")
            return

        if pos.direction != "flat" and pos.size > 0:
            logger.debug(f"Reconcile: position still open size={pos.size}")
            return

        # Exchange is flat — position was closed (SL/TP hit or manual)
        logger.info("Reconcile: exchange shows flat. Marking trade closed.")

        if self._position and self._open_trade_id:
            entry_price = self._position.get("entry_price", 0)
            direction = self._position.get("direction", "long")
            quantity = self._position.get("quantity", 0)
            sl = self._position.get("stop_loss", 0)
            tp = self._position.get("take_profit", 0)
            sl_order_id = self._position.get("sl_order_id")
            tp_order_id = self._position.get("tp_order_id")

            exit_price = None
            exit_reason = None

            # Query SL order status
            sl_status = None
            if sl_order_id:
                sl_status = self.exchange.get_order_status(self.cfg.symbol, sl_order_id)
                if sl_status.status == "filled":
                    exit_price = sl_status.fill_price
                    exit_reason = "sl_hit"

            # Query TP order status
            tp_status = None
            if tp_order_id:
                tp_status = self.exchange.get_order_status(self.cfg.symbol, tp_order_id)
                if tp_status.status == "filled":
                    exit_price = tp_status.fill_price
                    exit_reason = "tp_hit"

            # Cancel orphaned counterpart order
            if exit_reason == "sl_hit" and tp_order_id:
                if tp_status and tp_status.status == "open":
                    cancelled = self.exchange.cancel_order(self.cfg.symbol, tp_order_id)
                    logger.info(f"Cancelled orphaned TP order {tp_order_id}: {cancelled}")
            elif exit_reason == "tp_hit" and sl_order_id:
                if sl_status and sl_status.status == "open":
                    cancelled = self.exchange.cancel_order(self.cfg.symbol, sl_order_id)
                    logger.info(f"Cancelled orphaned SL order {sl_order_id}: {cancelled}")
            elif exit_reason is None:
                # Both orders unknown status — cancel both to be safe, use proximity heuristic
                if sl_order_id and sl_status and sl_status.status == "open":
                    self.exchange.cancel_order(self.cfg.symbol, sl_order_id)
                if tp_order_id and tp_status and tp_status.status == "open":
                    self.exchange.cancel_order(self.cfg.symbol, tp_order_id)

            # Fallback: proximity heuristic if order status didn't give us fill data
            if exit_price is None:
                fallback_price = self._get_last_close_price()
                if fallback_price and tp and sl:
                    if abs(fallback_price - tp) < abs(fallback_price - sl):
                        exit_reason = "tp_hit"
                    else:
                        exit_reason = "sl_hit"
                else:
                    exit_reason = "unknown"
                exit_price = fallback_price or entry_price
                logger.warning(f"Reconcile: using fallback exit_price={exit_price}, reason={exit_reason}")

            # PnL calculation
            if direction == "long":
                gross_pnl = (exit_price - entry_price) * quantity
            else:
                gross_pnl = (entry_price - exit_price) * quantity

            notional = exit_price * quantity
            fees = notional * (self.cfg.effective_fee_percent / 100)
            net_pnl = gross_pnl - fees

            self.repo.update_trade(self._open_trade_id, {
                "exit_price": exit_price,
                "exit_reason": exit_reason,
                "status": "closed",
                "pnl_usdt": round(gross_pnl, 4),
                "fees_usdt": round(fees, 4),
                "net_pnl_usdt": round(net_pnl, 4),
            })

            self.tg.send_close_alert(
                symbol=self.cfg.symbol,
                direction=direction,
                exit_reason=exit_reason,
                entry_price=entry_price,
                exit_price=exit_price,
                pnl_usdt=round(gross_pnl, 4),
                fees_usdt=round(fees, 4),
                net_pnl_usdt=round(net_pnl, 4),
            )

            self.repo.log_event("INFO", "trade_closed", f"Trade {self._open_trade_id} closed via reconcile",
                                {"exit_reason": exit_reason, "net_pnl": net_pnl})

        self._open_trade_id = None
        self._position = None
        self._original_sl = None
        self.state = BotState.IDLE

    def _get_last_close_price(self) -> float:
        """Get latest close price as fallback for exit price."""
        try:
            df = fetch_candles(self.cfg, self.cfg.ltf_interval)
            if df is not None and not df.empty:
                return df["close"].iloc[-1]
        except Exception:
            pass
        return 0.0

    # --------------------------------------------------------------- trailing SL

    def _manage_trailing_sl(self):
        """ATR-based trailing stop-loss. Moves SL favorably after 1R profit."""
        if not self._position or not self._open_trade_id:
            return

        direction = self._position.get("direction", "long")
        entry_price = self._position.get("entry_price", 0)
        current_sl = self._position.get("stop_loss", 0)
        quantity = self._position.get("quantity", 0)
        sl_order_id = self._position.get("sl_order_id")

        if not entry_price or not current_sl:
            return

        # Store original SL on first call for 1R calculation
        if self._original_sl is None:
            self._original_sl = current_sl

        # Fetch LTF candles to compute ATR
        ltf_df = fetch_candles(self.cfg, self.cfg.ltf_interval)
        if ltf_df is None or len(ltf_df) < self.cfg.atr_period + 1:
            return

        # Compute ATR(14)
        df = ltf_df.copy()
        df["prev_close"] = df["close"].shift(1)
        df["tr"] = df[["high", "prev_close"]].max(axis=1) - df[["low", "prev_close"]].min(axis=1)
        atr = df["tr"].iloc[-self.cfg.atr_period:].mean()

        if atr <= 0:
            return

        current_price = df["close"].iloc[-1]

        # Calculate 1R distance
        risk_1r = abs(entry_price - self._original_sl)
        if risk_1r == 0:
            return

        # Check if we've reached 1R profit
        if direction == "long":
            profit = current_price - entry_price
            if profit < risk_1r:
                return  # not yet at 1R, don't trail

            # Trail: new_sl = price - ATR * mult, but at least breakeven
            new_sl = current_price - atr * self.cfg.atr_trail_mult
            new_sl = max(new_sl, entry_price)  # at least breakeven

            # Only move SL up (favorably)
            if new_sl <= current_sl:
                return
        else:  # short
            profit = entry_price - current_price
            if profit < risk_1r:
                return

            new_sl = current_price + atr * self.cfg.atr_trail_mult
            new_sl = min(new_sl, entry_price)  # at least breakeven

            # Only move SL down (favorably)
            if new_sl >= current_sl:
                return

        new_sl = round(new_sl, 6)
        logger.info(f"Trailing SL: moving from {current_sl} to {new_sl} (ATR={atr:.6f})")

        # Cancel old SL order
        if sl_order_id:
            cancelled = self.exchange.cancel_order(self.cfg.symbol, sl_order_id)
            if not cancelled:
                logger.error(f"Failed to cancel old SL order {sl_order_id}")
                return

        # Place new SL order
        sl_side = "sell" if direction == "long" else "buy"
        new_sl_result = self.exchange.place_stop_order(
            self.cfg.symbol, sl_side, quantity, new_sl, reduce_only=True
        )

        if not new_sl_result.success:
            logger.critical(f"Trailing SL placement FAILED: {new_sl_result.error}")
            self.tg.send_critical_alert(
                f"TRAILING SL PLACEMENT FAILED!\n"
                f"Old SL was cancelled but new SL failed.\n"
                f"Error: {new_sl_result.error}\n"
                f"MANUAL ACTION REQUIRED. Bot paused."
            )
            self.state = BotState.ERROR_PAUSED
            self.repo.log_event("CRITICAL", "trailing_sl_failed",
                                f"SL placement failed after cancel: {new_sl_result.error}")
            return

        # Update DB and local state
        self.repo.update_trade(self._open_trade_id, {
            "stop_loss": new_sl,
            "sl_order_id": new_sl_result.order_id,
        })
        self._position["stop_loss"] = new_sl
        self._position["sl_order_id"] = new_sl_result.order_id

        self.tg.send(
            f"📐 <b>Trailing SL adjusted</b>\n"
            f"Old SL: <code>{current_sl:.6f}</code>\n"
            f"New SL: <code>{new_sl:.6f}</code>\n"
            f"ATR: <code>{atr:.6f}</code>\n"
            f"Price: <code>{current_price:.6f}</code>"
        )

        self.repo.log_event("INFO", "trailing_sl_moved",
                            f"SL moved from {current_sl} to {new_sl}",
                            {"old_sl": current_sl, "new_sl": new_sl, "atr": atr})

    # --------------------------------------------------------------- signal + entry

    def _signal_and_enter(self, now_utc: datetime):
        # 1. Fetch candles
        ltf_df = fetch_candles(self.cfg, self.cfg.ltf_interval)
        if ltf_df is None or ltf_df.empty:
            logger.warning("No LTF candles available. Skipping cycle.")
            self.repo.log_event("WARNING", "data_unavailable", "LTF candles unavailable")
            return

        # 2. Build HTF candles from LTF aggregation
        try:
            htf_df = build_htf_candles(ltf_df, self.cfg.htf_interval)
        except Exception as e:
            logger.warning(f"HTF aggregation failed: {e}")
            return

        if len(htf_df) < 20:
            logger.debug("Not enough HTF bars. Skipping.")
            return

        # 3. Compute HTF bias
        bias = compute_bias(htf_df, self.cfg.pivot_left_bars, self.cfg.pivot_right_bars)

        # 4. Build signal
        signal: Optional[Signal] = build_signal(self.cfg, ltf_df, bias, now_utc)
        if signal is None:
            return

        # 5. Compute sizing
        try:
            sizing = compute_sizing(self.cfg, signal.entry_price, signal.stop_loss)
        except ValueError as e:
            logger.warning(f"Sizing rejected: {e}")
            return

        # 6. Execute entry
        self._execute_entry(signal, sizing)

    # --------------------------------------------------------------- order execution

    def _execute_entry(self, signal: Signal, sizing):
        """Place entry + SL + TP orders. On SL failure → CRITICAL + pause."""
        symbol = self.cfg.symbol
        direction = signal.direction
        qty = sizing.quantity

        entry_side = "buy" if direction == "long" else "sell"
        sl_side = "sell" if direction == "long" else "buy"
        tp_side = "sell" if direction == "long" else "buy"

        self.state = BotState.PENDING_ENTRY

        # 1. Place market entry order
        entry_result = self.exchange.place_market_order(symbol, entry_side, qty)
        if not entry_result.success:
            logger.error(f"Entry order failed: {entry_result.error}")
            self.tg.send_error_alert(f"Entry order failed: {entry_result.error}")
            self.state = BotState.IDLE
            return

        actual_entry = entry_result.filled_price or signal.entry_price
        logger.info(f"Entry order placed: id={entry_result.order_id} price={actual_entry}")

        # 2. Place SL order (reduce-only)
        sl_result = self.exchange.place_stop_order(
            symbol, sl_side, qty, signal.stop_loss, reduce_only=True
        )
        if not sl_result.success:
            logger.critical(f"SL placement failed: {sl_result.error}")
            self.tg.send_critical_alert(
                f"SL PLACEMENT FAILED for {symbol} {direction.upper()}!\n"
                f"Error: {sl_result.error}\n"
                f"MANUAL ACTION REQUIRED. Bot paused."
            )
            self.state = BotState.ERROR_PAUSED
            return

        logger.info(f"SL order placed: id={sl_result.order_id} price={signal.stop_loss}")

        # 3. Place TP order (reduce-only limit)
        tp_result = self.exchange.place_limit_order(
            symbol, tp_side, qty, signal.take_profit, reduce_only=True
        )
        if not tp_result.success:
            logger.warning(f"TP placement failed: {tp_result.error}. Trade still active with SL only.")
            self.tg.send_error_alert(f"TP order failed (SL is active): {tp_result.error}")

        # 4. Persist trade to DB
        now_str = datetime.now(timezone.utc).isoformat()
        trade_row = {
            "signal_id": signal.signal_id,
            "timestamp_utc": now_str,
            "profile": self.cfg.profile,
            "exchange": self.cfg.exchange,
            "symbol": symbol,
            "direction": direction,
            "entry_price": actual_entry,
            "exit_price": None,
            "stop_loss": signal.stop_loss,
            "take_profit": signal.take_profit,
            "quantity": qty,
            "notional_usdt": sizing.notional_usdt,
            "margin_usdt": sizing.margin_usdt,
            "risk_budget_usdt": sizing.risk_budget_usdt,
            "leverage": self.cfg.leverage,
            "sizing_balance_inr": sizing.sizing_balance_inr,
            "est_fee_usdt": sizing.est_fee_usdt,
            "pnl_usdt": None,
            "fees_usdt": None,
            "net_pnl_usdt": None,
            "exit_reason": None,
            "status": "open",
            "sl_order_id": sl_result.order_id,
            "tp_order_id": tp_result.order_id if tp_result.success else None,
            "entry_order_id": entry_result.order_id,
        }
        trade_id = self.repo.insert_trade(trade_row)
        self._open_trade_id = trade_id
        self._position = {**trade_row, "id": trade_id}
        self._original_sl = signal.stop_loss
        self.state = BotState.OPEN

        # 5. Send entry alert
        self.tg.send_entry_alert(
            profile=self.cfg.profile,
            exchange=self.cfg.exchange,
            symbol=symbol,
            direction=direction,
            entry=actual_entry,
            sl=signal.stop_loss,
            tp=signal.take_profit,
            quantity=qty,
            leverage=self.cfg.leverage,
            sizing_mode=sizing.sizing_mode,
            sizing_balance_inr=sizing.sizing_balance_inr,
            risk_budget_usdt=sizing.risk_budget_usdt,
            notional_usdt=sizing.notional_usdt,
            margin_usdt=sizing.margin_usdt,
            est_fee_usdt=sizing.est_fee_usdt,
            rr=signal.rr_ratio,
        )

        self.repo.log_event("INFO", "trade_opened", f"Trade {trade_id} opened",
                            {"signal_id": signal.signal_id, "direction": direction,
                             "entry": actual_entry, "sl": signal.stop_loss, "tp": signal.take_profit})

    # --------------------------------------------------------------- Telegram commands

    def _cmd_start(self, args):
        self.paused = False
        self.tg.send("▶️ Bot resumed. Cycles active.")
        logger.info("Bot resumed via /start")

    def _cmd_stop(self, args):
        self.paused = True
        self.tg.send("⏸ Bot paused. No new entries. Existing position unaffected.")
        logger.info("Bot paused via /stop")

    def _cmd_status(self, args):
        pos = None
        if self._position:
            exchange_pos = self.exchange.get_position(self.cfg.symbol)
            if exchange_pos is not None:
                pos = {
                    "direction": exchange_pos.direction,
                    "size": exchange_pos.size,
                    "entry_price": exchange_pos.entry_price,
                    "unrealized_pnl": exchange_pos.unrealized_pnl,
                }
            else:
                pos = {"direction": "unknown", "size": 0, "entry_price": 0, "unrealized_pnl": 0}
        self.tg.send_status(
            state=self.state,
            profile=self.cfg.profile,
            exchange=self.cfg.exchange,
            symbol=self.cfg.symbol,
            leverage=self.cfg.leverage,
            position_info=pos,
        )

    def _cmd_trades(self, args):
        limit = 10
        if args:
            try:
                limit = int(args[0])
            except ValueError:
                pass
        trades = self.repo.get_recent_trades(limit)
        self.tg.send_trades_summary(trades)

    def _cmd_kill(self, args):
        logger.info("/kill received")
        self.state = BotState.CLOSING

        result = self.exchange.close_position(self.cfg.symbol)

        if result.error == "no_open_position":
            self.tg.send("ℹ️ <b>Kill:</b> No open position found on exchange.")
        elif result.success:
            self.tg.send(
                f"✅ <b>Kill:</b> Close order sent.\n"
                f"Order ID: <code>{result.order_id}</code>"
            )
            # Mark in DB
            if self._open_trade_id:
                self.repo.update_trade(self._open_trade_id, {
                    "exit_reason": "manual_kill",
                    "status": "closing",
                })
        else:
            self.tg.send(f"❌ <b>Kill failed:</b> {result.error}")
            self.state = BotState.OPEN
            return

        self.running = False
        self.state = BotState.IDLE

    def _cmd_shutdown(self, args):
        logger.info("/shutdown received")
        self.tg.send("🛑 <b>Graceful shutdown.</b> Bot stopping after current cycle.")
        self.running = False

    def _cmd_ltf5m(self, args):
        if self.state == BotState.OPEN:
            self.tg.send("❌ Cannot switch profile while position is open.")
            return
        self.cfg.profile = "ltf_5m"
        self.cfg._derive_profile_params()
        self.tg.send("✅ Profile switched to <b>ltf_5m</b>. Restart bot to apply.")
        logger.info("Profile switched to ltf_5m via Telegram")

    def _cmd_ltf15m(self, args):
        if self.state == BotState.OPEN:
            self.tg.send("❌ Cannot switch profile while position is open.")
            return
        self.cfg.profile = "ltf_15m"
        self.cfg._derive_profile_params()
        self.tg.send("✅ Profile switched to <b>ltf_15m</b>. Restart bot to apply.")
        logger.info("Profile switched to ltf_15m via Telegram")

    def _cmd_demo(self, args):
        if self.state == BotState.OPEN:
            self.tg.send("❌ Cannot switch exchange while position is open.")
            return
        self.cfg.exchange = "delta_demo"
        self.exchange = self._build_exchange()
        self.tg.send("✅ Switched to <b>delta_demo</b> exchange.")
        logger.info("Exchange switched to delta_demo via Telegram")

    def _cmd_live(self, args):
        if self.state == BotState.OPEN:
            self.tg.send("❌ Cannot switch exchange while position is open.")
            return
        self.cfg.exchange = "coinswitch_live"
        self.exchange = self._build_exchange()
        self.tg.send("✅ Switched to <b>coinswitch_live</b> exchange.")
        logger.info("Exchange switched to coinswitch_live via Telegram")
