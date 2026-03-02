# DevOps / Infrastructure Agent — CLAUDE.md
# Usage: cp this file to ./CLAUDE.md in project root

## Role
DevOps engineer deploying and operating a 24/7 trading bot
running on Delta Exchange (paper) and CoinSwitch Pro (live).

## Deployment Architecture
```
Server (VPS — Hetzner or DigitalOcean recommended)
  ├── docker-compose up
  │     ├── ada-delta-bot      ← ADA strategy on Delta Exchange
  │     ├── ada-coinswitch-bot ← ADA strategy on CoinSwitch live
  │     ├── xrp-coinswitch-bot ← XRP strategy on CoinSwitch live
  │     ├── dashboard-api      ← FastAPI monitoring
  │     ├── postgres           ← TimescaleDB (separate schemas per exchange)
  │     ├── redis              ← Signal queue
  │     ├── grafana            ← Dashboards
  │     └── prometheus         ← Metrics
  │
  └── Telegram Bot → your private channel (alerts)
```

## Exchange-Specific Environment Files
```bash
# Never mix these — separate .env files per instance
config/delta.env        ← Delta Exchange API keys (paper)
config/coinswitch.env   ← CoinSwitch API keys (live — handle with care)

# .gitignore must include:
config/delta.env
config/coinswitch.env
config/*.env
```

## Docker Compose Structure
```yaml
services:
  ada-delta-bot:
    env_file: config/delta.env
    environment:
      EXCHANGE: delta
      PAIR: ADAUSD
      MODE: validation  # No "paper" mode — this IS the validation instance

  ada-coinswitch-bot:
    env_file: config/coinswitch.env
    environment:
      EXCHANGE: coinswitch
      PAIR: ADAUSDT
      MODE: live

  xrp-coinswitch-bot:
    env_file: config/coinswitch.env
    environment:
      EXCHANGE: coinswitch
      PAIR: XRPUSDT
      MODE: live
```

## Uptime Requirements
- Target: 99.9% uptime (crypto markets run 24/7 — no weekends off)
- Graceful restart: must resume from last known state after crash
- Deployment window: ONLY between 22:00–00:00 UTC (lowest volume for ADA/XRP)
- NEVER deploy during: London Open (07:00–10:00), NY Open (12:00–15:00)
  These windows are defined by the strategy killzones in strategy.md (KILLZONES dict).
  Any change to killzone times there requires updating this deployment window.

## Critical Alerts (Telegram — immediate)
```
🚨 Bot process down (any instance)
🚨 Exchange connection lost > 30 seconds
🚨 Open position with no stop-loss detected
🚨 Daily drawdown limit breached
🚨 CoinSwitch API error on live order
🚨 Position state mismatch (bot vs exchange)
```

## Warning Alerts (Telegram — within 5 min)
```
⚠️ API rate limit > 80% consumed
⚠️ Data feed lag > 10 seconds
⚠️ Funding rate > 0.1% per 8h (adjust position sizing)
⚠️ XRP news event detected (pause XRP bot signal)
⚠️ Disk space > 80%
```

## Deployment Checklist (Before Any Deploy)
- [ ] Not during killzone hours (07:00–10:00 or 12:00–15:00 UTC)
- [ ] No open positions on CoinSwitch live
- [ ] Delta bot paused cleanly
- [ ] Config diffs reviewed — no accidental env var changes
- [ ] Rollback plan ready (previous Docker image tagged)
- [ ] Post-deploy: verify both exchanges reconnected within 60 seconds
