"""
HTF Bias Engine.
Detects swing pivots and derives market bias (bullish/bearish/neutral).

Bias logic:
- Bullish: last two confirmed swing highs form higher highs AND last two lows form higher lows.
- Bearish: last two confirmed swing lows form lower lows AND last two highs form lower highs.
- Neutral: no clear structure → no-trade.
"""

import logging
from typing import Literal, Optional

import pandas as pd

logger = logging.getLogger(__name__)

Bias = Literal["bullish", "bearish", "neutral"]


def _find_pivot_highs(df: pd.DataFrame, left: int, right: int) -> pd.Series:
    """Return boolean Series where True = confirmed pivot high."""
    highs = df["high"]
    n = len(highs)
    pivot = pd.Series(False, index=df.index)

    for i in range(left, n - right):
        window_left = highs.iloc[i - left:i]
        window_right = highs.iloc[i + 1:i + right + 1]
        if highs.iloc[i] >= window_left.max() and highs.iloc[i] >= window_right.max():
            pivot.iloc[i] = True

    return pivot


def _find_pivot_lows(df: pd.DataFrame, left: int, right: int) -> pd.Series:
    """Return boolean Series where True = confirmed pivot low."""
    lows = df["low"]
    n = len(lows)
    pivot = pd.Series(False, index=df.index)

    for i in range(left, n - right):
        window_left = lows.iloc[i - left:i]
        window_right = lows.iloc[i + 1:i + right + 1]
        if lows.iloc[i] <= window_left.min() and lows.iloc[i] <= window_right.min():
            pivot.iloc[i] = True

    return pivot


def compute_bias(df: pd.DataFrame, left_bars: int = 5, right_bars: int = 5) -> Bias:
    """
    Compute HTF bias from confirmed pivot swing structure.

    Parameters
    ----------
    df : HTF OHLCV DataFrame (UTC indexed, sorted ascending)
    left_bars : pivot confirmation bars to the left
    right_bars : pivot confirmation bars to the right

    Returns
    -------
    'bullish' | 'bearish' | 'neutral'
    """
    if len(df) < (left_bars + right_bars + 2) * 2:
        logger.debug("Not enough HTF bars to compute bias")
        return "neutral"

    pivot_highs_mask = _find_pivot_highs(df, left_bars, right_bars)
    pivot_lows_mask = _find_pivot_lows(df, left_bars, right_bars)

    ph_prices = df.loc[pivot_highs_mask, "high"].values
    pl_prices = df.loc[pivot_lows_mask, "low"].values

    if len(ph_prices) < 2 or len(pl_prices) < 2:
        logger.debug("Insufficient pivots to determine bias")
        return "neutral"

    last_ph = ph_prices[-1]
    prev_ph = ph_prices[-2]
    last_pl = pl_prices[-1]
    prev_pl = pl_prices[-2]

    higher_highs = last_ph > prev_ph
    higher_lows = last_pl > prev_pl
    lower_lows = last_pl < prev_pl
    lower_highs = last_ph < prev_ph

    if higher_highs and higher_lows:
        logger.debug(f"Bias: BULLISH (HH={last_ph:.5f}>={prev_ph:.5f}, HL={last_pl:.5f}>={prev_pl:.5f})")
        return "bullish"
    elif lower_lows and lower_highs:
        logger.debug(f"Bias: BEARISH (LL={last_pl:.5f}<={prev_pl:.5f}, LH={last_ph:.5f}<={prev_ph:.5f})")
        return "bearish"
    else:
        logger.debug("Bias: NEUTRAL (no clear structure)")
        return "neutral"
