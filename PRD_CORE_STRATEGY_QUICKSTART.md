# PRD: Core Trading Strategy + Engineer Quickstart

## 1. Purpose
This document explains the core strategy logic in a build-friendly way so engineers can implement it without ambiguity.
It also includes a quickstart execution plan.

## 2. Strategy Objective
Trade intraday continuation/retracement setups aligned with higher-timeframe structure using:
- HTF bias
- displacement confirmation
- FVG retracement entry
- fixed risk/reward exits

Market scope:
- Futures only (perpetual contracts), not spot.
- Signal candles must come from the same futures instrument family as execution.

Profiles supported:
- `ltf_5m`: LTF=5m, HTF=15m
- `ltf_15m`: LTF=15m, HTF=1h

## 3. Core Concepts
1. HTF Bias
- Identify directional structure from confirmed pivots.
- Bullish bias: sequence favors higher highs/higher lows.
- Bearish bias: sequence favors lower lows/lower highs.
- No clear structure => no trade.

2. Displacement
- Strong impulse candle required before entry.
- Rule: `abs(close-open) >= displacement_mult * ATR(14)`
- Suggested defaults:
  - 5m profile: `displacement_mult=1.8`
  - 15m profile: `displacement_mult=1.5`

3. Fair Value Gap (FVG)
- Bullish FVG on candle `i` if `low[i] > high[i-2]`
- Bearish FVG on candle `i` if `high[i] < low[i-2]`
- FVG expires after max age:
  - 5m: 24 bars
  - 15m: 20 bars

4. Entry Model
- Long:
  - HTF bias bullish
  - bullish displacement exists
  - valid bullish FVG exists
  - price retraces to configured fill level of FVG (`entry_percent=50`)
- Short: exact mirror logic.

5. Exit Model
- Stop loss: opposite FVG edge (or ATR fallback if enabled)
- Take profit: based on session RR policy
  - London peak (`07:00-10:00 UTC`): RR `1:2`
  - London-New York overlap (`13:00-16:00 UTC`): RR `1:4`
  - New York peak (`17:00-20:00 UTC`): RR `1:3`
- Resolve conflicts by precedence: overlap > NY peak > London peak.
- Reject signal if session RR cannot be resolved or if computed target is invalid.

## 4. Full Signal Pipeline (Step-by-Step)
For each cycle at candle close:
1. Fetch LTF futures candles for the configured symbol (minimum 300 bars).
2. Build HTF candles from LTF aggregation.
3. Compute ATR(14) on LTF.
4. Detect HTF pivots and derive bias.
5. If bias is neutral, return no-signal.
6. Detect latest displacement candle aligned with bias.
7. Detect active FVG aligned with bias and not expired.
8. Check retracement into FVG entry level.
9. Build candidate entry/sl/tp.
10. Compute RR and validate threshold.
11. Emit final `Signal` object or no-signal.

## 5. Risk and Sizing Rules
Inputs:
- `LEVERAGE` (fixed `3` in v1)
- `RISK_PER_TRADE_PERCENT` (e.g., 2)
- `USE_FIXED_CAPITAL` (must be `true` in v1)
- `FIXED_CAPITAL_INR` (fixed `1000` in v1)

Sizing balance:
- For demo/test and live in v1: `sizing_balance_inr = 1000`
- Do not auto-scale from wallet balance in v1

Formulas:
- `risk_budget = sizing_balance * leverage * (risk_pct/100)`
- `sl_distance = abs(entry - stop)`
- Delta qty: `floor(risk_budget/sl_distance)`, min 1
- CoinSwitch qty: `risk_budget/sl_distance`
- `notional = entry * qty`
- `margin = notional / leverage`

Fee model:
- Delta demo assumptions (paper analytics only): maker `0.05%`, taker `0.02%`.
- CoinSwitch live practical assumption (default):
  - `LIVE_TRADING_FEE_PERCENT = 0.20` (conservative upper bound in your 0.10% to 0.20% range)
  - `LIVE_TDS_PERCENT = 1.00`
  - `LIVE_TOTAL_COST_PERCENT = 1.20`
- Optional stress-test mode: set `LIVE_TOTAL_COST_PERCENT = 1.50`.
- Use `LIVE_TOTAL_COST_PERCENT` for pre-trade net expectancy checks and estimated net PnL.
- `est_total_cost = notional * (LIVE_TOTAL_COST_PERCENT/100)`

## 6. Runtime State Machine
States:
- `IDLE` (flat)
- `PENDING_ENTRY`
- `OPEN`
- `CLOSING`
- `ERROR_PAUSED`

Transitions:
1. `IDLE -> PENDING_ENTRY` when valid signal emitted.
2. `PENDING_ENTRY -> OPEN` when entry order acknowledged and position verified.
3. `OPEN -> IDLE` when exchange shows flat (SL/TP/manual close).
4. `OPEN -> CLOSING` on kill command.
5. `CLOSING -> IDLE` when close confirmed.
6. Any critical execution failure -> `ERROR_PAUSED`.

## 7. Exchange Reconciliation Rules
- Always trust exchange state over local memory.
- On every cycle, if local says open:
  - query exchange position
  - if size = 0 or no position, mark closed and clear local position
- Never send "closed" message without exchange-confirmed flat state (except explicit "close order sent" wording).

## 8. Telegram Alert Requirements
Entry alert must include:
- profile, exchange, symbol
- direction, entry, SL, TP
- quantity
- leverage
- sizing mode (`fixed_capital`/`paper_capital`/`exchange_wallet`)
- sizing balance
- risk budget
- notional
- margin

Kill alert outcomes (mutually exclusive):
- close order sent
- no open position
- exchange error
- mapping/validation error

## 9. Engineer Quickstart (Build Order)
1. Implement config loader and profile validation.
2. Implement candle fetch + HTF aggregation.
3. Implement pivot + bias engine.
4. Implement displacement + FVG detector.
5. Implement entry builder and RR filter.
6. Implement risk sizing module with fixed-capital mode.
7. Implement exchange adapters (Delta, CoinSwitch).
8. Implement bot cycle + state machine + reconciliation.
9. Implement Telegram commands/alerts.
10. Implement SQLite persistence and event logs.
11. Add retry/backoff wrapper for exchange calls.
12. Write tests and run paper test.

## 10. Test Checklist
- Unit: bias, FVG, displacement, RR, sizing formulas.
- Integration: open/reconcile/close lifecycle.
- Fault-path: SL order failure, exchange timeout, kill errors.
- Ops: restart bot with existing open position and recover correctly.

## 11. Deliverables
- working bot for both profiles
- `.env.example`
- migration/init SQL
- test report
- paper-trading validation summary

## 12. Implementation Notes
- Keep all timestamps UTC internally.
- Trigger only after candle close + 5s buffer.
- Enforce one open position at a time in v1.
- Reject exchange switch while in position.
- Do not mix spot candles with futures execution. If exchange-native futures candles are unavailable, use Binance USD-M futures as fallback reference feed (never Binance spot).
- Include estimated and realized fees in alerts/logs.
- Lock symbol to `ADAUSDT` perpetual in v1.
- Use fixed capital `1000 INR` for both demo and live in v1.
- Use session-based RR policy (London 07:00-10:00=1:2, overlap 13:00-16:00=1:4, NY 17:00-20:00=1:3).
