"""
Telegram alert module.
Handles all outbound Telegram messages and inbound command polling.
"""

import logging
import time
from typing import Callable, Dict, Optional

import requests

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"


class TelegramBot:

    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self._last_update_id = 0
        self._handlers: Dict[str, Callable] = {}
        self._base = f"{TELEGRAM_API}/bot{token}"

    # ---------------------------------------------------------- send

    def send(self, text: str, parse_mode: str = "HTML"):
        try:
            resp = requests.post(
                f"{self._base}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": parse_mode,
                },
                timeout=10,
            )
            resp.raise_for_status()
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")

    # ---------------------------------------------------------- templates

    def send_entry_alert(
        self,
        profile: str,
        exchange: str,
        symbol: str,
        direction: str,
        entry: float,
        sl: float,
        tp: float,
        quantity: float,
        leverage: int,
        sizing_mode: str,
        sizing_balance_inr: float,
        risk_budget_usdt: float,
        notional_usdt: float,
        margin_usdt: float,
        est_fee_usdt: float,
        rr: float,
    ):
        arrow = "🟢 LONG" if direction == "long" else "🔴 SHORT"
        msg = (
            f"<b>{arrow} | {symbol} | {profile.upper()}</b>\n"
            f"Exchange: <b>{exchange}</b>\n\n"
            f"Entry:    <code>{entry:.5f}</code>\n"
            f"SL:       <code>{sl:.5f}</code>\n"
            f"TP:       <code>{tp:.5f}</code>\n"
            f"RR:       <b>1:{rr:.1f}</b>\n\n"
            f"Qty:      <code>{quantity}</code>\n"
            f"Leverage: <code>{leverage}x</code>\n"
            f"Mode:     <code>{sizing_mode}</code>\n"
            f"Balance:  <code>₹{sizing_balance_inr:.0f}</code>\n"
            f"Risk:     <code>${risk_budget_usdt:.4f}</code>\n"
            f"Notional: <code>${notional_usdt:.4f}</code>\n"
            f"Margin:   <code>${margin_usdt:.4f}</code>\n"
            f"Est. Fee: <code>${est_fee_usdt:.4f}</code>"
        )
        self.send(msg)

    def send_close_alert(
        self,
        symbol: str,
        direction: str,
        exit_reason: str,
        entry_price: float,
        exit_price: float,
        pnl_usdt: float,
        fees_usdt: float,
        net_pnl_usdt: float,
    ):
        pnl_icon = "✅" if net_pnl_usdt >= 0 else "❌"
        msg = (
            f"<b>{pnl_icon} CLOSED | {symbol}</b>\n"
            f"Direction:  <code>{direction.upper()}</code>\n"
            f"Reason:     <code>{exit_reason}</code>\n\n"
            f"Entry:      <code>{entry_price:.5f}</code>\n"
            f"Exit:       <code>{exit_price:.5f}</code>\n\n"
            f"Gross PnL:  <code>${pnl_usdt:.4f}</code>\n"
            f"Fees:       <code>${fees_usdt:.4f}</code>\n"
            f"Net PnL:    <b>${net_pnl_usdt:.4f}</b>"
        )
        self.send(msg)

    def send_error_alert(self, message: str):
        self.send(f"⚠️ <b>ERROR</b>\n{message}")

    def send_critical_alert(self, message: str):
        self.send(f"🚨 <b>CRITICAL</b>\n{message}")

    def send_status(
        self,
        state: str,
        profile: str,
        exchange: str,
        symbol: str,
        leverage: int,
        position_info: Optional[dict] = None,
    ):
        pos_str = "Flat (no open position)"
        if position_info and position_info.get("direction") != "flat":
            pos_str = (
                f"{position_info['direction'].upper()} | "
                f"qty={position_info['size']} | "
                f"entry={position_info['entry_price']:.5f} | "
                f"uPnL=${position_info.get('unrealized_pnl', 0):.4f}"
            )
        msg = (
            f"<b>📊 Bot Status</b>\n"
            f"State:    <code>{state}</code>\n"
            f"Profile:  <code>{profile}</code>\n"
            f"Exchange: <code>{exchange}</code>\n"
            f"Symbol:   <code>{symbol}</code>\n"
            f"Leverage: <code>{leverage}x</code>\n\n"
            f"Position: {pos_str}"
        )
        self.send(msg)

    def send_trades_summary(self, trades: list):
        if not trades:
            self.send("No trades found.")
            return
        lines = ["<b>📋 Recent Trades</b>\n"]
        for t in trades:
            pnl = t.get("net_pnl_usdt")
            pnl_str = f"${pnl:.4f}" if pnl is not None else "open"
            icon = "✅" if (pnl or 0) >= 0 else "❌"
            lines.append(
                f"{icon} <code>{t.get('direction','').upper()}</code> "
                f"entry=<code>{t.get('entry_price',0):.5f}</code> "
                f"exit=<code>{t.get('exit_price') or '-'}</code> "
                f"pnl=<b>{pnl_str}</b> "
                f"[{t.get('exit_reason',t.get('status',''))}]"
            )
        self.send("\n".join(lines))

    # ---------------------------------------------------------- command polling

    def register_command(self, command: str, handler: Callable):
        self._handlers[command.lower()] = handler

    def poll_commands(self):
        """Poll for new Telegram commands. Call in a loop."""
        try:
            resp = requests.get(
                f"{self._base}/getUpdates",
                params={"offset": self._last_update_id + 1, "timeout": 5},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            for update in data.get("result", []):
                self._last_update_id = update["update_id"]
                msg = update.get("message", {})
                text = msg.get("text", "")
                if not text.startswith("/"):
                    continue
                parts = text.strip().split()
                cmd = parts[0].lower().lstrip("/")
                # Strip @botname suffix if present
                cmd = cmd.split("@")[0]
                args = parts[1:] if len(parts) > 1 else []
                handler = self._handlers.get(cmd)
                if handler:
                    try:
                        handler(args)
                    except Exception as e:
                        logger.error(f"Command handler /{cmd} failed: {e}")
                        self.send(f"Error handling /{cmd}: {e}")
        except Exception as e:
            logger.warning(f"Telegram poll error: {e}")
