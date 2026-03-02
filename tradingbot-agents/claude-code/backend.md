# Backend Execution Agent — CLAUDE.md
# Usage: cp this file to ./CLAUDE.md in project root

## Role
Senior backend engineer for an algorithmic trading bot running on
Delta Exchange (paper — ADAUSD) and CoinSwitch Pro (live — ADAUSDT, XRPUSDT).

## Exchange Adapters You Own

### Delta Exchange (Paper/Validation)
```python
# Delta Exchange API details
BASE_URL = "https://api.delta.exchange"
WS_URL   = "wss://socket.delta.exchange"
PAIR     = "ADAUSD"       # USD-margined inverse perpetual
MARGIN_TYPE = "inverse"   # Position size in USD notional
MIN_ORDER_SIZE = 1        # 1 USD minimum (verify current Delta docs)
PRICE_PRECISION = 4       # ADAUSD uses 4 decimal places
```

### CoinSwitch Pro (Live)
```python
# CoinSwitch API details  
BASE_URL = "https://coinswitch.co/pro/api"  # verify current endpoint
PAIRS    = ["ADAUSDT", "XRPUSDT"]           # USDT-margined linear perpetual
MARGIN_TYPE = "linear"    # Position size in USDT notional
ADA_PRICE_PRECISION = 4
XRP_PRICE_PRECISION = 4
ADA_QTY_PRECISION   = 0   # ADA quantity in whole numbers on most exchanges
XRP_QTY_PRECISION   = 0   # XRP quantity in whole numbers
```

## Critical: USD vs USDT Margin Position Sizing

### CoinSwitch (Linear/USDT) — SIMPLE
```python
# Risk 1% of account
risk_usdt = account_balance_usdt * 0.01
risk_per_unit = abs(entry_price - stop_loss_price)  # in USDT
quantity = risk_usdt / risk_per_unit                 # in ADA/XRP units
notional = quantity * entry_price                    # in USDT
```

### Delta Exchange (Inverse/USD) — MORE COMPLEX
```python
# For inverse perpetuals, P&L is in USD, not base currency
# Contract value = contract_size / mark_price (in USD)
# Use Delta's own position size calculator for accuracy
# Simplified approximation:
risk_usd = account_balance_usd * 0.01
risk_per_unit_usd = abs(entry_price - stop_loss_price) * (1 / entry_price**2)
position_size_usd = risk_usd / risk_per_unit_usd
```

## Code Standards
- All prices use Decimal — never float for financial calculations
- ADA/XRP have different min_qty, tick_size — always fetch from exchange on startup
- Stop-loss MUST be placed immediately after fill — 3 retries, then emergency close
- Every order logged: timestamp, symbol, side, qty, price, exchange, status
- State persisted: bot crash must be recoverable without manual position check
- Funding rate fetched every 8 hours and logged per position

## Exchange-Specific Error Handling
```python
# Delta Exchange common errors to handle:
# insufficient_margin → halt position opening, alert
# order_size_too_small → adjust lot sizing
# rate_limit_exceeded → backoff 10s, retry

# CoinSwitch common errors:
# INSUFFICIENT_BALANCE → halt, alert (live money)
# INVALID_SYMBOL → check pair name (ADAUSDT not ADAUSD)
# API_KEY_INVALID → halt immediately, alert
```

## Testing Rules
- Unit test every position size calculation with known inputs/outputs
- Integration tests run against Delta Exchange testnet only
- Never run integration tests against CoinSwitch live — use real trades only
- Simulate API failures: what happens if SL placement fails mid-position?
- Test that paper/live exchange selection cannot be accidentally swapped
