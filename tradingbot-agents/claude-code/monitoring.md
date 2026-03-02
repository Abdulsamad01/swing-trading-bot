# Monitoring & Performance Agent — CLAUDE.md
# Usage: cp this file to ./CLAUDE.md in project root

## Role
SRE for a 24/7 trading bot running on Delta Exchange (ADA validation)
and CoinSwitch Pro (ADA + XRP live).

## What to Monitor Per Instance

### Delta Exchange Instance (ADA Validation)
- Bot process: alive?
- ADAUSD WebSocket: connected and receiving candles?
- Signal rate: are signals being generated? (0 signals for > 4h = possible bug)
- Trade performance: win rate, P&L vs expectation
- No live money here — downtime is bad but not financially critical

### CoinSwitch Live Instances (ADA + XRP)
- Bot process: alive? (critical — live money)
- ADAUSDT + XRPUSDT WebSocket: connected? (critical)
- Open positions: any position without a stop-loss? (critical — halt immediately)
- Daily P&L vs drawdown limits (critical)
- Funding rate: checked every 8h and logged?
- XRP news filter: operational? (important)

## Grafana Dashboard Layout
```
Row 1 — Live Status
  ├── CoinSwitch ADA bot: [ACTIVE / PAUSED / HALTED]
  ├── CoinSwitch XRP bot: [ACTIVE / PAUSED / HALTED]
  ├── Delta ADA bot:      [ACTIVE / PAUSED / HALTED]
  └── Exchange connections: [CONNECTED / DISCONNECTED]

Row 2 — Live P&L (CoinSwitch)
  ├── Today's P&L (USDT)
  ├── Weekly P&L (USDT)
  ├── Open positions + unrealized P&L
  └── Drawdown meter (current vs 5% daily limit)

Row 3 — Validation P&L (Delta)
  ├── Delta ADA P&L (USD)
  ├── Delta vs CoinSwitch performance comparison
  └── Signal count today

Row 4 — Trade Stats (Rolling 20 trades)
  ├── Win rate — ADA (CoinSwitch)
  ├── Win rate — XRP (CoinSwitch)
  ├── Win rate — ADA (Delta)
  └── Average R achieved

Row 5 — System Health
  ├── WebSocket latency per exchange
  ├── API rate limit usage
  ├── Candle processing lag
  └── Memory and CPU
```

## Alert Thresholds

### Critical (Telegram — immediate)
```python
CRITICAL_ALERTS = {
    "bot_down":           "Any bot process stopped",
    "no_stoploss":        "CoinSwitch open position without SL detected",
    "daily_dd_breach":    "Daily DD hit 5% on CoinSwitch",
    "weekly_dd_breach":   "Weekly DD hit 10% on CoinSwitch",
    "exchange_disconnect": "WebSocket down > 30 seconds",
    "position_mismatch":  "Bot state ≠ CoinSwitch actual position",
}
```

### Warning (Telegram — within 5 min)
```python
WARNING_ALERTS = {
    "ada_no_signals_4h":    "ADA no signals generated in 4 hours",
    "xrp_no_signals_6h":    "XRP no signals in 6h (fewer setups expected)",
    "funding_rate_high":    "Funding rate > 0.1% per 8h on any pair",
    "daily_dd_80pct":       "Daily DD at 4% (80% of limit)",
    "delta_coinswitch_gap": "Delta and CoinSwitch performance diverging > 20%",
}
```

## Performance Targets (Altcoin Futures)
- Signal detection latency: < 200ms after candle close
- Order placement latency: < 1000ms from signal to order (altcoins have wider spreads)
- WebSocket reconnect: < 10 seconds
- State reconciliation: every 60 seconds
