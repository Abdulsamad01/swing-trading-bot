# ICT/SMC Strategy Agent — CLAUDE.md
# Usage: cp this file to ./CLAUDE.md in project root

## Role
Expert ICT/SMC strategy engineer writing precise trading logic
for ADA (Cardano) and XRP (Ripple) perpetual futures.

## Asset Configuration
```python
ASSETS = {
    "ADA": {
        "delta_pair":      "ADAUSD",    # Delta Exchange (paper)
        "coinswitch_pair": "ADAUSDT",   # CoinSwitch (live)
        "price_decimals":  4,
        "ob_min_move_multiplier": 1.5,  # 1.5x avg body for OB qualification
        "fvg_min_gap_pct": 0.05,        # 0.05% minimum FVG size
        "liquidity_tolerance_pct": 0.03, # 0.03% for equal highs/lows
        "ob_max_visits": 2,             # Mitigate after 2 visits
        "sessions": ["london", "new_york"],  # Best sessions for ADA
    },
    "XRP": {
        "delta_pair":      None,         # XRP not on Delta (only ADA)
        "coinswitch_pair": "XRPUSDT",   # CoinSwitch only
        "price_decimals":  4,
        "ob_min_move_multiplier": 2.0,  # 2x avg body (XRP moves faster)
        "fvg_min_gap_pct": 0.08,        # 0.08% minimum FVG size
        "liquidity_tolerance_pct": 0.05,
        "ob_max_visits": 1,             # XRP OBs rarely hold second visit
        "sessions": ["new_york"],       # NY only for XRP (best volume)
        "news_filter": True,            # Mandatory XRP news check
    }
}
```

## Timeframe Setup
```python
HTF = "4h"   # Bias timeframe — market structure direction
ITF = "1h"   # Confirmation timeframe — order flow
LTF = "15m"  # Entry timeframe — precise entry at OB/FVG
```

## Killzones (UTC)
```python
KILLZONES = {
    "london":   ("07:00", "10:00"),  # ADA: good. XRP: moderate
    "new_york": ("12:00", "15:00"),  # Both: best
    "ny_close": ("20:00", "22:00"),  # Both: moderate (creates next day OBs)
    # Asia session: avoid ADA/XRP — too low volume
}
```

## Signal Quality Rules
- Signal must have HTF 4H bias + ITF 1H confirmation + LTF 15M entry
- Minimum R:R: 2.0 — hard reject anything below
- XRP: check news filter before generating signal
- ADA: skip if within 2 hours of staking epoch boundary
- Both: skip if ATR ratio > 2.5 (extreme volatility — avoid)

## Code Patterns
```python
# Always separate ADA and XRP strategy instances
ada_engine  = StrategyEngine(asset="ADA", config=ASSETS["ADA"])
xrp_engine  = StrategyEngine(asset="XRP", config=ASSETS["XRP"])

# Never mix asset configs
# Each asset has its own: OB detector, FVG detector, liquidity tracker

# Signal validation pattern
def validate_signal(signal: TradeSignal, asset: str) -> bool:
    if asset == "XRP" and not news_filter_clear():
        return False
    if calculate_atr_ratio(signal, asset) < Decimal("0.5"):
        return False  # reject low-ATR signals early
    if signal.risk_reward < Decimal("2.0"):
        return False
    if not in_valid_killzone(asset):
        return False
    return True
```

## Testing Strategy Code
```python
# All tests must specify ADA or XRP — no generic tests
def test_ada_bullish_ob_detection():
    # Build ADA-specific synthetic candles
    # Use ADA price range (0.3–0.8 USDT typical)
    candles = build_ada_candles(...)
    detector = OrderBlockDetector(config=ASSETS["ADA"])
    ...

def test_xrp_ob_mitigated_after_one_visit():
    # XRP OBs mitigate after 1 visit (not 2 like ADA)
    ...
```
