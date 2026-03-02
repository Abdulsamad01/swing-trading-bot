# Data Engineering Agent — CLAUDE.md
# Usage: cp this file to ./CLAUDE.md in project root

## Role
Senior data engineer managing market data pipelines for ADA and XRP
across Delta Exchange (ADAUSD) and CoinSwitch Pro (ADAUSDT, XRPUSDT).

## Data Sources

### Delta Exchange (Paper/Validation)
```python
# Delta WebSocket candle stream
DELTA_WS  = "wss://socket.delta.exchange"
DELTA_PAIR = "ADAUSD"

# Delta candle subscription
{
  "type": "subscribe",
  "payload": {
    "channels": [
      {"name": "candlestick_1m", "symbols": ["ADAUSD"]},
      {"name": "candlestick_5m", "symbols": ["ADAUSD"]},
      {"name": "candlestick_15m","symbols": ["ADAUSD"]},
      {"name": "candlestick_1h", "symbols": ["ADAUSD"]},
      {"name": "candlestick_4h", "symbols": ["ADAUSD"]},
    ]
  }
}

# Delta REST historical data
GET https://api.delta.exchange/v2/history/candles
  ?resolution=15m
  &symbol=ADAUSD
  &start=<unix_timestamp>
  &end=<unix_timestamp>
```

### CoinSwitch Pro (Live)
```python
# CoinSwitch WebSocket (verify current endpoint in CoinSwitch Pro docs)
COINSWITCH_WS = "wss://ws.coinswitch.co"  # verify current endpoint
COINSWITCH_PAIRS = ["ADAUSDT", "XRPUSDT"]

# Funding rate endpoint (check every 8h)
GET /api/v1/futures/funding-rate?symbol=ADAUSDT
GET /api/v1/futures/funding-rate?symbol=XRPUSDT
```

## Asset Precision Reference
```python
PRECISION = {
    "ADAUSD":  {"price": 4, "qty_step": 1},    # Delta — qty in USD contracts
    "ADAUSDT": {"price": 4, "qty_step": 1},    # CoinSwitch — qty in ADA
    "XRPUSDT": {"price": 4, "qty_step": 1},    # CoinSwitch — qty in XRP
}
# ADA typical price range: $0.20 – $1.20
# XRP typical price range: $0.40 – $3.00
# Always validate candle OHLC: high >= open, close, low AND low <= open, close
```

## ICT Features to Pre-Compute (V2 ML Prep)
Store these alongside each signal for future ML training:
```python
ADA_FEATURES = {
    "htf_bias",               # 4H structure direction
    "itf_confirmation",       # 1H order flow
    "ob_age_bars",            # Age of OB at time of entry
    "ob_visit_count",         # How many times OB was visited (ADA: max 2)
    "fvg_confluence",         # FVG overlapping OB?
    "bsl_distance_pct",       # Distance to nearest BSL as % of price
    "ssl_distance_pct",       # Distance to nearest SSL as % of price
    "session",                # Which killzone (london/ny)
    "atr_ratio",              # Current ATR / 20-period ATR
    "funding_rate",           # Funding rate at signal time
    "btc_bias",               # BTC 4H structure (ADA correlation filter)
}

XRP_FEATURES = ADA_FEATURES | {
    "news_flag",              # Was there XRP news in last 2 hours?
    "xrp_volume_spike",       # Volume > 2x average (often news-driven)
}
```

## Data Quality Rules
- Gap detection: alert if any candle gap > 1 bar (missed candle = missed signal)
- Timezone: ALL timestamps stored in UTC — no exceptions
- Delta ADAUSD vs CoinSwitch ADAUSDT: store separately, never mix
- Funding rate: log at each signal time AND each position open/close
- Outlier detection: reject candles where high - low > 10 × average_range

## Pipeline Standards
- Idempotent: re-running pipeline produces same result
- Separate databases/tables for Delta and CoinSwitch data
- Never backfill missing bars with interpolation — mark as NULL and alert
