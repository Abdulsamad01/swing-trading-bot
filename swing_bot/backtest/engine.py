"""
Backtest engine.
Replays historical candles bar-by-bar through the full signal pipeline.
No lookahead bias: signal at bar N → entry simulated at bar N close price.
SL/TP checked on each subsequent bar's high/low.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

import pandas as pd

from config.settings import Config
from data.market_data import build_htf_candles
from strategy.bias_engine import compute_bias
from strategy.entry_engine import build_signal, Signal
from strategy.risk_engine import compute_sizing

logger = logging.getLogger(__name__)

# Minimum warm-up bars needed before we start evaluating signals
WARMUP_BARS = 100


@dataclass
class BacktestTrade:
    run_id: str
    bar_index: int
    timestamp_utc: datetime
    direction: str
    entry_price: float
    exit_price: float
    stop_loss: float
    take_profit: float
    quantity: float
    notional_usdt: float
    risk_budget_usdt: float
    rr_ratio: float
    gross_pnl_usdt: float
    fees_usdt: float
    net_pnl_usdt: float
    exit_reason: str        # 'tp_hit' | 'sl_hit' | 'end_of_data'
    bars_held: int
    session: str            # 'london' | 'overlap' | 'ny' | 'unknown'


@dataclass
class BacktestResult:
    run_id: str
    profile: str
    symbol: str
    start_date: str
    end_date: str
    trades: List[BacktestTrade] = field(default_factory=list)

    # --- summary (filled by engine after run) ---
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    gross_pnl_usdt: float = 0.0
    total_fees_usdt: float = 0.0
    net_pnl_usdt: float = 0.0
    max_drawdown_usdt: float = 0.0
    best_trade_usdt: float = 0.0
    worst_trade_usdt: float = 0.0
    avg_rr: float = 0.0


def _resolve_session(cfg: Config, dt: datetime) -> str:
    t = dt.strftime("%H:%M")
    if cfg.overlap_start_utc <= t < cfg.overlap_end_utc:
        return "overlap"
    if cfg.ny_peak_start_utc <= t < cfg.ny_peak_end_utc:
        return "ny"
    if cfg.london_peak_start_utc <= t < cfg.london_peak_end_utc:
        return "london"
    return "outside"


def _simulate_exit(
    ltf_df: pd.DataFrame,
    entry_bar: int,
    direction: str,
    stop_loss: float,
    take_profit: float,
) -> tuple[float, str, int]:
    """
    Walk forward from entry_bar+1 and check if SL or TP is hit.
    Returns (exit_price, exit_reason, bars_held).
    Uses candle high/low to detect breach — no lookahead.
    """
    for i in range(entry_bar + 1, len(ltf_df)):
        high = ltf_df["high"].iloc[i]
        low = ltf_df["low"].iloc[i]
        close = ltf_df["close"].iloc[i]
        bars_held = i - entry_bar

        if direction == "long":
            if low <= stop_loss:
                return stop_loss, "sl_hit", bars_held
            if high >= take_profit:
                return take_profit, "tp_hit", bars_held
        else:  # short
            if high >= stop_loss:
                return stop_loss, "sl_hit", bars_held
            if low <= take_profit:
                return take_profit, "tp_hit", bars_held

    # End of data — exit at last close
    last_close = ltf_df["close"].iloc[-1]
    return last_close, "end_of_data", len(ltf_df) - entry_bar - 1


def run_backtest(
    cfg: Config,
    ltf_df: pd.DataFrame,
    start_date: str,
    end_date: str,
) -> BacktestResult:
    """
    Run full backtest on provided LTF candle DataFrame.

    Parameters
    ----------
    cfg        : Config object (profile, strategy params, fee model, etc.)
    ltf_df     : Full historical LTF OHLCV DataFrame (UTC, sorted ascending)
    start_date : 'YYYY-MM-DD' string (for labeling)
    end_date   : 'YYYY-MM-DD' string (for labeling)

    Returns
    -------
    BacktestResult with all trades and summary statistics.
    """
    run_id = str(uuid.uuid4())[:8]
    result = BacktestResult(
        run_id=run_id,
        profile=cfg.profile,
        symbol=cfg.symbol,
        start_date=start_date,
        end_date=end_date,
    )

    n = len(ltf_df)
    logger.info(f"Backtest started: run_id={run_id} bars={n} profile={cfg.profile}")

    in_trade = False
    skip_until_bar = 0  # skip bars while in a trade

    for i in range(WARMUP_BARS, n):
        if in_trade or i < skip_until_bar:
            continue

        # Build rolling window up to bar i (inclusive) — no lookahead
        window_ltf = ltf_df.iloc[:i + 1].copy().reset_index(drop=True)

        # Build HTF from LTF window
        try:
            htf_df = build_htf_candles(window_ltf, cfg.htf_interval)
        except Exception:
            continue

        if len(htf_df) < 20:
            continue

        # Compute bias on HTF
        bias = compute_bias(htf_df, cfg.pivot_left_bars, cfg.pivot_right_bars)

        # Get signal timestamp from bar i
        bar_time = ltf_df["timestamp_utc"].iloc[i]
        if hasattr(bar_time, "to_pydatetime"):
            bar_time = bar_time.to_pydatetime()

        # Build signal
        signal: Optional[Signal] = build_signal(cfg, window_ltf, bias, bar_time)
        if signal is None:
            continue

        # Compute sizing
        try:
            sizing = compute_sizing(cfg, signal.entry_price, signal.stop_loss)
        except ValueError:
            continue

        # Entry at bar i close price (no lookahead)
        entry_price = ltf_df["close"].iloc[i]

        # Recalculate SL/TP relative to actual entry
        sl_distance = abs(entry_price - signal.stop_loss)
        if sl_distance <= 0:
            continue

        stop_loss = signal.stop_loss
        take_profit = signal.take_profit

        # Simulate exit by walking forward
        exit_price, exit_reason, bars_held = _simulate_exit(
            ltf_df, i, signal.direction, stop_loss, take_profit
        )

        # PnL calculation
        if signal.direction == "long":
            gross_pnl = (exit_price - entry_price) * sizing.quantity
        else:
            gross_pnl = (entry_price - exit_price) * sizing.quantity

        notional = entry_price * sizing.quantity
        fees = notional * (cfg.effective_fee_percent / 100.0)
        net_pnl = gross_pnl - fees

        session = _resolve_session(cfg, bar_time)

        trade = BacktestTrade(
            run_id=run_id,
            bar_index=i,
            timestamp_utc=bar_time,
            direction=signal.direction,
            entry_price=round(entry_price, 6),
            exit_price=round(exit_price, 6),
            stop_loss=round(stop_loss, 6),
            take_profit=round(take_profit, 6),
            quantity=round(sizing.quantity, 4),
            notional_usdt=round(notional, 4),
            risk_budget_usdt=round(sizing.risk_budget_usdt, 4),
            rr_ratio=round(signal.rr_ratio, 2),
            gross_pnl_usdt=round(gross_pnl, 4),
            fees_usdt=round(fees, 4),
            net_pnl_usdt=round(net_pnl, 4),
            exit_reason=exit_reason,
            bars_held=bars_held,
            session=session,
        )
        result.trades.append(trade)

        logger.debug(
            f"Bar {i} | {signal.direction.upper()} | entry={entry_price:.5f} "
            f"exit={exit_price:.5f} reason={exit_reason} net_pnl={net_pnl:.4f}"
        )

        # Skip forward past this trade's duration
        skip_until_bar = i + bars_held + 1

    # Compute summary statistics
    _compute_summary(result)
    logger.info(
        f"Backtest complete: {result.total_trades} trades | "
        f"win_rate={result.win_rate:.1f}% | net_pnl=${result.net_pnl_usdt:.4f}"
    )
    return result


def _compute_summary(result: BacktestResult):
    trades = result.trades
    if not trades:
        return

    result.total_trades = len(trades)
    result.winning_trades = sum(1 for t in trades if t.net_pnl_usdt > 0)
    result.losing_trades = sum(1 for t in trades if t.net_pnl_usdt <= 0)
    result.win_rate = round(result.winning_trades / result.total_trades * 100, 2)
    result.gross_pnl_usdt = round(sum(t.gross_pnl_usdt for t in trades), 4)
    result.total_fees_usdt = round(sum(t.fees_usdt for t in trades), 4)
    result.net_pnl_usdt = round(sum(t.net_pnl_usdt for t in trades), 4)
    result.best_trade_usdt = round(max(t.net_pnl_usdt for t in trades), 4)
    result.worst_trade_usdt = round(min(t.net_pnl_usdt for t in trades), 4)
    result.avg_rr = round(sum(t.rr_ratio for t in trades) / len(trades), 2)

    # Max drawdown: largest peak-to-trough drop in cumulative net PnL
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in trades:
        cumulative += t.net_pnl_usdt
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd
    result.max_drawdown_usdt = round(max_dd, 4)
