# PRD: Standalone 5m/15m Intraday Trading Bot

## 1. Document Control
- Document ID: PRD-LTF-001
- Version: 2.0 (Standalone Build Spec)
- Date: February 26, 2026
- Audience: Backend engineer, quant engineer, QA engineer, DevOps
- Goal: Build a production-ready intraday bot from this document alone, without referencing any existing repository.

## 2. Product Goal
Build an automated crypto futures intraday trading system for lower timeframes (5m and 15m) with:
- deterministic strategy rules
- strict risk sizing
- futures-native market data and execution
- exchange execution + reconciliation
- Telegram control plane
- persistent trade/state logs

Primary deployment target:
- Single symbol at a time (v1), locked to `ADAUSDT` perpetual
- Exchanges: Delta Exchange India (demo for testing) and CoinSwitch (live for production)

## 3. Out of Scope (v1)
- Multi-symbol parallel execution
- Portfolio-level risk aggregation
- Dynamic ML-based parameter optimization
- Web dashboard

## 4. Success Criteria (Acceptance)
System is accepted only if all pass:
1. Bot runs continuously 7 days without process crash in test environment.
2. No false "position closed" alert when exchange position is still open.
3. Every opened trade includes sizing report (capital, leverage, risk budget, notional, margin).
4. Kill command closes open position or reports precise failure reason.
5. Backtest and forward-test reports can be generated for each profile with gross PnL, fees, and net PnL.
6. Trades are opened and closed in real time with exchange-confirmed reconciliation.

## 5. User Stories
1. As an operator, I can run `5m` or `15m` profile from config for `ADAUSDT` perpetual.
2. As an operator, I can cap trade sizing to fixed capital (`1000 INR`) in both demo and live.
3. As an operator, I can pause, resume, kill, and inspect status via Telegram.
4. As an operator, I can audit every trade from DB logs.
5. As an operator, I can safely switch exchange only when flat.

## 6. High-Level Architecture
### 6.1 Venue Policy (India Deployment)
- Testing/demo environment: Delta Exchange India demo account only.
- Live environment: CoinSwitch only.
- Exchange switch is allowed only when flat (no open position).

Implement these modules exactly:
1. `config/`
- Loads env + profile settings.
- Validates mandatory keys.

2. `data/market_data.py`
- Fetches OHLCV candles from futures markets only (never spot).
- Returns pandas DataFrame with UTC index.

3. `strategy/`
- `bias_engine.py`
- `entry_engine.py`
- `risk_engine.py`
- Must produce deterministic `Signal` object.

4. `execution/`
- `delta_client.py`
- `coinswitch_client.py`
- Unified adapter interface for place/cancel/get/close/positions.

5. `bot/core.py`
- Main cycle scheduler.
- Position state machine.
- Signal -> order execution flow.

6. `bot/alerts.py`
- Telegram send + formatting.

7. `storage/repository.py`
- SQLite for trades, bot_state, events.

8. `ops/`
- startup script, service file, health checks.

## 7. Data Contracts
### 7.1 Candle Schema
### 7.1A Market Data Source Rules
1. Data must be futures OHLCV, never spot OHLCV.
2. Signal symbol must match execution symbol semantics (e.g., `ADAUSDT` perpetual feed for `ADAUSDT` perpetual trading).
3. If fallback feed is used, log an `events` warning with source and reason.
4. If neither primary nor fallback futures feed is available, skip cycle (no-trade) and alert degraded data mode after repeated failures.

Fields per candle:
- `source_market` (string: `futures`)
- `timestamp_utc` (datetime, candle close time)
- `open` (float)
- `high` (float)
- `low` (float)
- `close` (float)
- `volume` (float)

### 7.2 Signal Schema
- `signal_id` (string UUID)
- `profile` (`ltf_5m` or `ltf_15m`)
- `symbol` (string)
- `timestamp_utc` (datetime)
- `direction` (`long` or `short`)
- `entry_price` (float)
- `stop_loss` (float)
- `take_profit` (float)
- `rr_ratio` (float)
- `reason` (string)

### 7.3 Position Schema (runtime)
- `exchange` (string)
- `symbol` (string)
- `direction` (string)
- `entry_price` (float)
- `stop_loss` (float)
- `take_profit` (float)
- `quantity` (float)
- `order_id` (string/int)
- `product_id` (optional int)
- `entry_time_utc` (datetime)
- `profile` (string)

### 7.4 Database Tables
Create tables:
1. `trades`
- `id` INTEGER PK
- `timestamp_utc` TEXT
- `profile` TEXT
- `exchange` TEXT
- `symbol` TEXT
- `direction` TEXT
- `entry_price` REAL
- `exit_price` REAL NULL
- `stop_loss` REAL
- `take_profit` REAL
- `quantity` REAL
- `notional_usdt` REAL
- `margin_usdt` REAL
- `risk_budget_usdt` REAL
- `leverage` INTEGER
- `pnl_usdt` REAL NULL
- `fees_usdt` REAL NULL
- `exit_reason` TEXT
- `status` TEXT
- `created_at` TEXT DEFAULT CURRENT_TIMESTAMP

2. `bot_state`
- `key` TEXT PK
- `value` TEXT
- `updated_at` TEXT

3. `events`
- `id` INTEGER PK
- `timestamp_utc` TEXT
- `level` TEXT
- `event_type` TEXT
- `message` TEXT
- `context_json` TEXT

## 8. Strategy Specification (Deterministic)
Implement exactly these steps.

### 8.1 Profiles
- `ltf_5m`
  - LTF = 5m
  - HTF = 15m
  - cycle interval = every 5 minutes
- `ltf_15m`
  - LTF = 15m
  - HTF = 1h
  - cycle interval = every 15 minutes

### 8.2 Session Filter (UTC)
Allow entries only during:
- 08:00 to 20:00 UTC
Reject entries outside window.

### 8.3 HTF Bias Rule
Compute last confirmed HTF swing structure.
- Bias = `bullish` if latest confirmed swing high and higher low sequence is intact.
- Bias = `bearish` if latest confirmed swing low and lower high sequence is intact.
- Else no-trade.

Pivot parameters:
- `left_bars = 5`
- `right_bars = 5`

### 8.4 Displacement Filter
Define candle body displacement:
- `abs(close - open) >= displacement_mult * ATR(14)`
Use:
- `displacement_mult = 1.5` for 15m profile
- `displacement_mult = 1.8` for 5m profile

### 8.5 Fair Value Gap (FVG) Detection
Bullish FVG at candle `i` if:
- `low[i] > high[i-2]`
Bearish FVG at candle `i` if:
- `high[i] < low[i-2]`

Store gap bounds and age in bars.
Reject if age > `max_fvg_age`:
- 5m profile: 24 bars
- 15m profile: 20 bars

### 8.6 Entry Trigger
Long setup:
1. HTF bias bullish
2. Valid bullish displacement candle
3. Active bullish FVG not expired
4. Current price retraces into FVG by `entry_percent`:
   - `entry_percent = 50`

Short setup mirrors above.

### 8.7 Stop Loss and Take Profit
- SL = opposite edge of FVG (or fixed ATR fallback if disabled)
- TP = entry + RR * risk_distance (long)
- TP = entry - RR * risk_distance (short)

### 8.8 Session-Based RR Policy (UTC)
- London peak session (`07:00-10:00 UTC`): use `RR = 2` (1:2)
- London-New York overlap (`13:00-16:00 UTC`): use `RR = 4` (1:4)
- New York peak session (`17:00-20:00 UTC`): use `RR = 3` (1:3)
- Precedence when windows conflict: overlap > New York peak > London peak
- Outside configured session windows: no-trade in v1
- Reject signal if session RR is undefined.

## 9. Risk and Position Sizing
### 9.1 Inputs
- `LEVERAGE` (fixed `3` in v1)
- `RISK_PER_TRADE_PERCENT` (default 2.0)
- `USE_FIXED_CAPITAL` (must be `true` in v1)
- `FIXED_CAPITAL_INR` (fixed `1000` in v1)

### 9.2 Sizing Balance
In v1 for both demo and live:
- `sizing_balance_inr = FIXED_CAPITAL_INR`
- default and required value: `1000`
- Do not use wallet-balance sizing in v1

### 9.3 Risk Budget Formula
`risk_budget_usdt = sizing_balance * leverage * (risk_per_trade_percent / 100)`

### 9.4 Quantity Formula
`sl_distance = abs(entry_price - stop_loss)`
Reject if `sl_distance <= 0`.

Quantity:
- Delta contracts: `qty = floor(risk_budget_usdt / sl_distance)` and minimum 1
- CoinSwitch quantity: `qty = risk_budget_usdt / sl_distance`

### 9.5 Derived Logging Fields
- `notional_usdt = entry_price * quantity`
- `margin_usdt = notional_usdt / leverage`

### 9.6 Fee and Tax Model
Delta Exchange India demo (paper only):
- `DELTA_MAKER_FEE_PERCENT = 0.05`
- `DELTA_TAKER_FEE_PERCENT = 0.02`
- Used for simulated fee analytics in demo mode only.

CoinSwitch live (practical default):
- `COINSWITCH_TRADING_FEE_PERCENT = 0.20`
- `COINSWITCH_TDS_PERCENT = 1.00`
- `COINSWITCH_TOTAL_COST_PERCENT = 1.20`
- Optional stress mode: `COINSWITCH_TOTAL_COST_PERCENT = 1.50`

Formulas:
- `entry_cost = entry_notional * (effective_cost_percent / 100)`
- `exit_cost = exit_notional * (effective_cost_percent / 100)` (if applicable by venue/accounting policy)
- `fees_usdt` stores combined fees/tax converted to quote terms for PnL accounting
- `net_pnl_usdt = gross_pnl_usdt - fees_usdt`

Policy:
- Keep all fee/tax values configurable in `.env`.
- Default live operation uses `COINSWITCH_TOTAL_COST_PERCENT = 1.20` for practical realism.
## 10. Execution Rules
### 10.1 Pre-Trade Guardrails
Reject trade if:
1. Existing open position exists.
2. Exchange mode invalid.
3. Symbol mapping/product ID missing.
4. Leverage set call fails hard.
5. Effective fee+tax estimate must be included in pre-trade report.

### 10.2 Order Placement
1. Place market entry order.
2. Place protective SL reduce-only.
3. Place TP reduce-only.
4. If SL placement fails: send CRITICAL alert and pause new entries.

### 10.3 Position Reconciliation (Every Cycle)
- Always query exchange position state for exchange-backed modes.
- If exchange reports flat while local says open:
  - mark trade closed with `exit_reason=exchange_closed`
  - clear runtime position
  - send closure alert

### 10.4 Kill Flow
On `/kill`:
1. Attempt close position via exchange API.
2. Parse response and alert one of:
- close order sent
- no open position
- exchange error
- mapping/validation error
3. Stop scheduler loop.

## 11. Telegram Interface
Commands required:
- `/start` - resume cycles
- `/stop` - pause cycles
- `/status` - runtime status, profile, symbol, leverage, open position
- `/trades` - recent N trades summary
- `/kill` - emergency close and shutdown
- `/shutdown` - graceful stop without forced close
- `/profile <ltf_5m|ltf_15m>` - switch profile only when flat

### 11.1 Entry Alert Template (must include)
- profile
- exchange
- symbol
- direction
- entry/sl/tp
- quantity
- leverage
- sizing mode (`fixed_capital` / `paper_capital` / `exchange_wallet`)
- sizing balance
- risk budget
- notional
- margin
- estimated fees+tax

## 12. Scheduler and Candle Timing
- Trigger cycle at exact timeframe boundaries + 5 seconds buffer.
- Example for 5m: 00:00:05, 00:05:05, 00:10:05 UTC.
- Never evaluate partially formed candle.

## 13. Configuration File Spec (.env)
Mandatory:
- `EXCHANGE` = `delta_testnet|delta_live|coinswitch`
- `SYMBOL` = `ADAUSDT` (locked in v1)
- `MARKET_TYPE` = `futures` (must be `futures` in v1)
- `LEVERAGE` = `3` (fixed in v1)
- `PROFILE` = `ltf_5m|ltf_15m`
- `USE_FIXED_CAPITAL` = `true` (fixed in v1)
- `FIXED_CAPITAL_INR` = `1000`
- `RISK_PER_TRADE_PERCENT` = float
- `DELTA_MAKER_FEE_PERCENT` = float (default `0.05`)
- `DELTA_TAKER_FEE_PERCENT` = float (default `0.02`)
- `COINSWITCH_TRADING_FEE_PERCENT` = float (default `0.20`)
- `COINSWITCH_TDS_PERCENT` = float (default `1.00`)
- `COINSWITCH_TOTAL_COST_PERCENT` = float (default `1.20`, optional stress `1.50`)
- Exchange API keys/secrets
- Telegram token/chat id

## 14. Error Handling and Retries
- Implement retry wrapper with exponential backoff for API calls.
- Defaults:
  - max retries: 3
  - base delay: 1.0s
  - jitter: +/-20%
- Log every retry attempt in `events` table.

## 15. Security and Safety
- Enforce startup check: abort if any data connector is configured for spot candles.
- Never log API secret.
- Redact tokens in exception messages.
- Validate config at startup and fail fast.
- Do not allow exchange switch when position open.

## 16. Testing Plan
### 16.1 Unit Tests
- FVG detection
- bias classification
- RR computation
- sizing formulas
- scheduler boundary behavior

### 16.2 Integration Tests (mock exchange)
- open -> reconcile -> close lifecycle
- SL placement failure path
- kill success and kill failure responses
- fixed capital sizing enforcement

### 16.3 Paper Forward Test
- Run on testnet for minimum 7 days per profile.
- Capture trade count, win rate, max drawdown, alert correctness.

## 17. Rollout Plan
1. Build complete feature set in branch.
2. Run unit + integration tests.
3. Deploy to Delta Exchange India demo with `PROFILE=ltf_15m` first.
4. After stable 7 days, run `ltf_5m` with same capital cap.
5. Promote to live with smallest capital cap.

## 18. Deliverables Checklist
- [ ] Config loader + validation
- [ ] Data fetcher
- [ ] Strategy engine per this PRD
- [ ] Exchange adapters
- [ ] Core bot loop and state machine
- [ ] Telegram controller
- [ ] SQLite repository
- [ ] Tests (unit + integration)
- [ ] Deployment scripts
- [ ] Runbook and incident guide

## 19. Definition of Done
Project is done when:
1. All checklist items complete.
2. Acceptance criteria in Section 4 pass.
3. Paper forward-test report attached.
4. Operator can run, monitor, and stop bot only via docs + .env without code edits.
