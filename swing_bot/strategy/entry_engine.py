"""
Entry Engine.
Detects displacement candles, Fair Value Gaps, and builds entry signals.

Pipeline:
1. Compute ATR(14) on LTF
2. Find displacement candle aligned with bias
3. Find active FVG aligned with bias (not expired)
4. Check if current price has retraced into FVG at entry_percent level
5. Return entry_price, stop_loss, take_profit, or None
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd

from config.settings import Config
from strategy.bias_engine import Bias

logger = logging.getLogger(__name__)


@dataclass
class FVG:
    index: int                  # bar index where FVG was formed
    direction: str              # 'bullish' | 'bearish'
    gap_high: float             # top of the gap
    gap_low: float              # bottom of the gap
    age_bars: int               # bars since formation


@dataclass
class Signal:
    signal_id: str
    profile: str
    symbol: str
    timestamp_utc: datetime
    direction: str              # 'long' | 'short'
    entry_price: float
    stop_loss: float
    take_profit: float
    rr_ratio: float
    reason: str


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Compute Average True Range."""
    high = df["high"]
    low = df["low"]
    close = df["close"].shift(1)

    tr = pd.concat([
        high - low,
        (high - close).abs(),
        (low - close).abs(),
    ], axis=1).max(axis=1)

    atr = tr.ewm(span=period, min_periods=period).mean()
    return atr


def find_displacement(
    df: pd.DataFrame,
    atr: pd.Series,
    bias: Bias,
    displacement_mult: float,
) -> Optional[int]:
    """
    Find the most recent displacement candle aligned with bias.
    Returns bar index or None.

    Displacement: abs(close - open) >= displacement_mult * ATR(14)
    Direction alignment:
      - bullish: close > open (bullish candle)
      - bearish: close < open (bearish candle)
    """
    body = (df["close"] - df["open"]).abs()
    threshold = atr * displacement_mult

    # Look back last 50 bars (not including the very last partially-formed one)
    lookback = min(50, len(df) - 1)
    candidates = df.index[-(lookback):-1]  # exclude last (current forming) bar

    result_idx = None
    for idx in reversed(candidates):
        if pd.isna(atr.loc[idx]) or pd.isna(body.loc[idx]):
            continue
        if body.loc[idx] < threshold.loc[idx]:
            continue
        if bias == "bullish" and df.loc[idx, "close"] <= df.loc[idx, "open"]:
            continue
        if bias == "bearish" and df.loc[idx, "close"] >= df.loc[idx, "open"]:
            continue
        result_idx = idx
        break

    return result_idx


def find_active_fvg(
    df: pd.DataFrame,
    bias: Bias,
    max_fvg_age: int,
) -> Optional[FVG]:
    """
    Find the most recent active FVG aligned with bias, not expired.

    Bullish FVG at candle i: low[i] > high[i-2]
    Bearish FVG at candle i: high[i] < low[i-2]

    The gap is between high[i-2] and low[i] (bullish) or low[i-2] and high[i] (bearish).
    Age is counted from bar i to current bar index.
    """
    n = len(df)
    current_bar = n - 1  # last confirmed closed bar

    # Scan backwards from most recent, skipping the current forming bar
    for i in range(current_bar, 1, -1):
        age = current_bar - i
        if age > max_fvg_age:
            break

        if bias == "bullish":
            gap_low = df["low"].iloc[i]
            gap_high = df["high"].iloc[i - 2]
            if gap_low > gap_high:
                return FVG(
                    index=i,
                    direction="bullish",
                    gap_high=gap_low,    # top of gap = current bar's low
                    gap_low=gap_high,    # bottom of gap = candle i-2's high
                    age_bars=age,
                )

        elif bias == "bearish":
            gap_high = df["high"].iloc[i]
            gap_low = df["low"].iloc[i - 2]
            if gap_high < gap_low:
                return FVG(
                    index=i,
                    direction="bearish",
                    gap_high=gap_low,    # top of gap = candle i-2's low
                    gap_low=gap_high,    # bottom of gap = current bar's high
                    age_bars=age,
                )

    return None


def _resolve_session_rr(cfg: Config, now_utc: datetime) -> Optional[float]:
    """
    Determine RR ratio based on current UTC time and session windows.
    Precedence: overlap > NY peak > London peak.
    Returns None if outside all configured windows.
    """
    t = now_utc.strftime("%H:%M")

    def in_window(start: str, end: str) -> bool:
        return start <= t < end

    in_overlap = in_window(cfg.overlap_start_utc, cfg.overlap_end_utc)
    in_ny = in_window(cfg.ny_peak_start_utc, cfg.ny_peak_end_utc)
    in_london = in_window(cfg.london_peak_start_utc, cfg.london_peak_end_utc)

    if in_overlap:
        return cfg.rr_overlap
    if in_ny:
        return cfg.rr_ny
    if in_london:
        return cfg.rr_london

    return None


def build_signal(
    cfg: Config,
    ltf_df: pd.DataFrame,
    bias: Bias,
    now_utc: Optional[datetime] = None,
) -> Optional[Signal]:
    """
    Run the full entry pipeline and return a Signal or None.

    Steps:
    1. Check bias
    2. Check session window
    3. Compute ATR
    4. Find displacement candle
    5. Find active FVG
    6. Check retracement into FVG
    7. Compute SL, TP, RR
    8. Return Signal
    """
    if bias == "neutral":
        logger.debug("No signal: bias is neutral")
        return None

    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    # Session filter
    if cfg.session_only_trading:
        rr = _resolve_session_rr(cfg, now_utc)
        if rr is None:
            logger.debug(f"No signal: outside session windows at {now_utc.strftime('%H:%M')} UTC")
            return None
    else:
        rr = cfg.rr_london  # fallback default

    atr = compute_atr(ltf_df, cfg.atr_period)

    # Find displacement
    disp_idx = find_displacement(ltf_df, atr, bias, cfg.displacement_mult)
    if disp_idx is None:
        logger.debug("No signal: no displacement candle found")
        return None

    # Find active FVG
    fvg = find_active_fvg(ltf_df, bias, cfg.max_fvg_age)
    if fvg is None:
        logger.debug("No signal: no active FVG found")
        return None

    # FVG must be AFTER the displacement candle
    if fvg.index <= disp_idx:
        logger.debug("No signal: FVG is not after displacement candle")
        return None

    # Compute entry level (midpoint of FVG at entry_percent)
    fvg_range = fvg.gap_high - fvg.gap_low
    if fvg_range <= 0:
        logger.debug("No signal: FVG range is zero or negative")
        return None

    entry_percent = cfg.entry_percent / 100.0

    if bias == "bullish":
        # Entry = bottom of gap + entry_percent * range (price retraces down into gap)
        entry_price = fvg.gap_low + (1.0 - entry_percent) * fvg_range
        current_price = ltf_df["close"].iloc[-1]
        # Price must have retraced into gap at or below entry level
        if current_price > entry_price:
            logger.debug(f"No signal: price {current_price:.5f} has not retraced to entry {entry_price:.5f}")
            return None
        stop_loss = fvg.gap_low  # opposite edge of FVG
        risk_distance = entry_price - stop_loss
        if risk_distance <= 0:
            logger.debug("No signal: risk distance <= 0")
            return None
        take_profit = entry_price + rr * risk_distance
        direction = "long"

    else:  # bearish
        # Entry = top of gap - entry_percent * range (price retraces up into gap)
        entry_price = fvg.gap_high - (1.0 - entry_percent) * fvg_range
        current_price = ltf_df["close"].iloc[-1]
        if current_price < entry_price:
            logger.debug(f"No signal: price {current_price:.5f} has not retraced to entry {entry_price:.5f}")
            return None
        stop_loss = fvg.gap_high  # opposite edge of FVG
        risk_distance = stop_loss - entry_price
        if risk_distance <= 0:
            logger.debug("No signal: risk distance <= 0")
            return None
        take_profit = entry_price - rr * risk_distance
        direction = "short"

    actual_rr = abs(take_profit - entry_price) / risk_distance

    signal = Signal(
        signal_id=str(uuid.uuid4()),
        profile=cfg.profile,
        symbol=cfg.symbol,
        timestamp_utc=now_utc,
        direction=direction,
        entry_price=round(entry_price, 6),
        stop_loss=round(stop_loss, 6),
        take_profit=round(take_profit, 6),
        rr_ratio=round(actual_rr, 2),
        reason=f"bias={bias} fvg_age={fvg.age_bars} rr={rr}",
    )

    logger.info(
        f"Signal: {direction.upper()} {cfg.symbol} "
        f"entry={signal.entry_price} sl={signal.stop_loss} tp={signal.take_profit} RR={signal.rr_ratio}"
    )
    return signal
