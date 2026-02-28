# Config Schema (v1)

## Core Constraints
- `MARKET_TYPE` must be `futures`.
- `SYMBOL` must be `ADAUSDT`.
- `LEVERAGE` must be `3`.
- `USE_FIXED_CAPITAL` must be `true`.
- `FIXED_CAPITAL_INR` must be `1000`.
- One open position at a time.

## Field Definitions
- `ENVIRONMENT`: enum(`demo`, `live`)
- `EXCHANGE`: enum(`delta_demo`, `coinswitch_live`)
- `MARKET_TYPE`: enum(`futures`)
- `SYMBOL`: enum(`ADAUSDT`)
- `PROFILE`: enum(`ltf_5m`, `ltf_15m`)
- `LEVERAGE`: int, allowed=`3`
- `USE_FIXED_CAPITAL`: bool, allowed=`true`
- `FIXED_CAPITAL_INR`: float, allowed=`1000`
- `RISK_PER_TRADE_PERCENT`: float, min>0, recommended `2.0`

## Session RR Fields (UTC)
- `LONDON_PEAK_START_UTC` / `LONDON_PEAK_END_UTC`: `HH:MM`, default `07:00`-`10:00`
- `OVERLAP_START_UTC` / `OVERLAP_END_UTC`: `HH:MM`, default `13:00`-`16:00`
- `NY_PEAK_START_UTC` / `NY_PEAK_END_UTC`: `HH:MM`, default `17:00`-`20:00`
- `RR_LONDON`: float, default `2`
- `RR_OVERLAP`: float, default `4`
- `RR_NY`: float, default `3`
- `SESSION_ONLY_TRADING`: bool, default `true`

## Strategy Fields
- `ENTRY_PERCENT`: float in `[0, 100]`, default `50`
- `PIVOT_LEFT_BARS`: int >=1, default `5`
- `PIVOT_RIGHT_BARS`: int >=1, default `5`
- `ATR_PERIOD`: int >=1, default `14`
- `DISPLACEMENT_MULT_5M`: float >0, default `1.8`
- `DISPLACEMENT_MULT_15M`: float >0, default `1.5`
- `MAX_FVG_AGE_5M`: int >=1, default `24`
- `MAX_FVG_AGE_15M`: int >=1, default `20`

## Fee & Tax Fields
- `DELTA_MAKER_FEE_PERCENT`: float >=0, default `0.05`
- `DELTA_TAKER_FEE_PERCENT`: float >=0, default `0.02`
- `COINSWITCH_TRADING_FEE_PERCENT`: float >=0, default `0.20`
- `COINSWITCH_TDS_PERCENT`: float >=0, default `1.00`
- `COINSWITCH_TOTAL_COST_PERCENT`: float >=0, default `1.20` (optional stress `1.50`)

Validation rule:
- `COINSWITCH_TOTAL_COST_PERCENT` should equal `COINSWITCH_TRADING_FEE_PERCENT + COINSWITCH_TDS_PERCENT` unless explicit override mode is enabled.

## Data & Runtime Fields
- `DATA_SOURCE_PRIMARY`: enum(`exchange_futures`)
- `DATA_SOURCE_FALLBACK`: enum(`binance_usdm_futures`)
- `CANDLE_LIMIT`: int >=300
- `CANDLE_CLOSE_BUFFER_SECONDS`: int >=1, default `5`
- `MAX_RETRIES`: int >=0, default `3`
- `RETRY_BASE_DELAY_SECONDS`: float >0, default `1.0`
- `RETRY_JITTER_PERCENT`: float in `[0, 100]`, default `20`

## Secrets
- `TELEGRAM_BOT_TOKEN`: required non-empty string
- `TELEGRAM_CHAT_ID`: required non-empty string
- `DELTA_DEMO_API_KEY`: required when `EXCHANGE=delta_demo`
- `DELTA_DEMO_API_SECRET`: required when `EXCHANGE=delta_demo`
- `COINSWITCH_API_KEY`: required when `EXCHANGE=coinswitch_live`
- `COINSWITCH_API_SECRET`: required when `EXCHANGE=coinswitch_live`

## Storage
- `SQLITE_PATH`: required writable path
- `LOG_LEVEL`: enum(`DEBUG`, `INFO`, `WARNING`, `ERROR`), default `INFO`
