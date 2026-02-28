"""
Unit tests for strategy modules: bias, FVG, displacement, RR, sizing.
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timezone

from strategy.bias_engine import compute_bias
from strategy.entry_engine import compute_atr, find_active_fvg, find_displacement
from strategy.risk_engine import compute_sizing


# ------------------------------------------------------------------ helpers

def make_df(closes, highs=None, lows=None, opens=None):
    n = len(closes)
    if highs is None:
        highs = [c + 0.005 for c in closes]
    if lows is None:
        lows = [c - 0.005 for c in closes]
    if opens is None:
        opens = closes
    timestamps = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")
    return pd.DataFrame({
        "timestamp_utc": timestamps,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": [1000.0] * n,
        "source_market": "futures",
    })


# ------------------------------------------------------------------ bias tests

def test_bias_bullish():
    # Create clear higher highs and higher lows
    closes = list(range(100, 160))
    df = make_df(closes)
    bias = compute_bias(df, left_bars=3, right_bars=3)
    assert bias == "bullish"


def test_bias_bearish():
    closes = list(range(160, 100, -1))
    df = make_df(closes)
    bias = compute_bias(df, left_bars=3, right_bars=3)
    assert bias == "bearish"


def test_bias_neutral_insufficient_bars():
    closes = [100.0] * 5
    df = make_df(closes)
    bias = compute_bias(df, left_bars=3, right_bars=3)
    assert bias == "neutral"


# ------------------------------------------------------------------ ATR tests

def test_atr_positive():
    closes = [float(100 + i) for i in range(50)]
    df = make_df(closes)
    atr = compute_atr(df, period=14)
    # ATR values after warmup period should be positive
    valid_atr = atr.dropna()
    assert (valid_atr > 0).all()


# ------------------------------------------------------------------ FVG tests

def test_bullish_fvg_detected():
    # candle i-2 high = 0.50, candle i low = 0.60 → bullish FVG
    highs = [0.40, 0.50, 0.45, 0.60, 0.65] * 10
    lows  = [0.35, 0.45, 0.40, 0.55, 0.60] * 10
    closes = [0.42, 0.48, 0.44, 0.62, 0.63] * 10
    df = make_df(closes, highs=highs, lows=lows)
    fvg = find_active_fvg(df, bias="bullish", max_fvg_age=30)
    assert fvg is not None
    assert fvg.direction == "bullish"
    assert fvg.gap_low < fvg.gap_high


def test_no_fvg_when_expired():
    closes = [1.0] * 60
    highs = [1.01] * 60
    lows = [0.99] * 60
    df = make_df(closes, highs=highs, lows=lows)
    fvg = find_active_fvg(df, bias="bullish", max_fvg_age=5)
    assert fvg is None


# ------------------------------------------------------------------ sizing tests

class MockCfg:
    exchange = "delta_demo"
    leverage = 3
    risk_per_trade_percent = 2.0
    fixed_capital_inr = 1000.0
    delta_taker_fee_percent = 0.02
    coinswitch_total_cost_percent = 1.20

    @property
    def effective_fee_percent(self):
        return self.delta_taker_fee_percent * 2


def test_sizing_basic():
    cfg = MockCfg()
    result = compute_sizing(cfg, entry_price=0.5000, stop_loss=0.4900)
    assert result.quantity >= 1
    assert result.risk_budget_usdt > 0
    assert result.notional_usdt > 0
    assert result.margin_usdt == pytest.approx(result.notional_usdt / cfg.leverage, rel=1e-3)


def test_sizing_zero_sl_raises():
    cfg = MockCfg()
    with pytest.raises(ValueError):
        compute_sizing(cfg, entry_price=0.5, stop_loss=0.5)


def test_sizing_min_qty_one():
    cfg = MockCfg()
    # Very small SL distance should still give qty >= 1
    result = compute_sizing(cfg, entry_price=100.0, stop_loss=99.999)
    assert result.quantity >= 1
