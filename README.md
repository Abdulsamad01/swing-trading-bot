# Swing Trade Bot

Automated ICT/SMC-based swing trading bot for **ADAUSDT perpetual futures** with Telegram control, multi-exchange support, and backtesting.

## Strategy

Uses **Inner Circle Trader (ICT) / Smart Money Concepts (SMC)**:

- **Multi-timeframe analysis** — HTF for market bias, LTF for entries
- **Bias detection** — Swing pivot structure (Higher Highs/Higher Lows = bullish, Lower Lows/Lower Highs = bearish)
- **Entry** — Displacement candle + Fair Value Gap (FVG) retracement at 50%
- **Session-aware RR** — London 2:1, London-NY Overlap 4:1, NY 3:1
- **Risk management** — Fixed capital, configurable leverage and risk per trade

### Profiles

| Profile | LTF | HTF | Displacement Mult | Max FVG Age |
|---------|-----|-----|--------------------|-------------|
| `ltf_5m` | 5m | 15m | 1.8 | 24 bars |
| `ltf_15m` | 15m | 1h | 1.5 | 20 bars |

## Supported Exchanges

| Exchange | Mode | Notes |
|----------|------|-------|
| **Delta Exchange India** | Demo + Live | Integer contracts, testnet available |
| **CoinSwitch Pro** | Live | Decimal quantities, India-focused |

**Data sources**: Delta Exchange (primary), Binance USD-M Futures (fallback). Always futures, never spot.

## Project Structure

```
swing_bot/
├── main.py                # Entry point
├── run_backtest.py        # CLI backtest runner
├── requirements.txt
├── .env                   # Your API keys (not committed)
├── config/
│   └── settings.py        # Config from .env with validation
├── strategy/
│   ├── bias_engine.py     # HTF bias via swing pivots
│   ├── entry_engine.py    # Displacement + FVG signal generation
│   └── risk_engine.py     # Position sizing
├── execution/
│   ├── base.py            # Abstract exchange interface
│   ├── delta_client.py    # Delta Exchange adapter
│   ├── coinswitch_client.py  # CoinSwitch adapter
│   └── retry.py           # Exponential backoff retry
├── data/
│   └── market_data.py     # OHLCV fetcher (Delta + Binance fallback)
├── bot/
│   ├── core.py            # State machine, scheduler, order execution
│   └── alerts.py          # Telegram bot integration
├── storage/
│   └── repository.py      # SQLite persistence
├── backtest/
│   ├── engine.py          # Bar-by-bar backtest engine
│   ├── historical_data.py # Binance historical data fetcher
│   └── report.py          # Report generator
└── tests/
    └── test_strategy.py   # Unit tests
```

## Setup

### 1. Clone and install

```bash
git clone https://github.com/<your-username>/swing-trade-bot.git
cd swing-trade-bot/swing_bot
python -m venv venv
source venv/bin/activate        # Linux/Mac
# venv\Scripts\activate         # Windows
pip install -r requirements.txt
```

### 2. Configure environment

Copy and edit the `.env` file:

```bash
cp .env.example .env
```

Required keys:

```env
# Exchange API keys
DELTA_API_KEY=your_key
DELTA_API_SECRET=your_secret
COINSWITCH_API_KEY=your_key
COINSWITCH_SECRET_KEY=your_secret

# Telegram
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# Bot config
EXCHANGE=delta_demo          # delta_demo or coinswitch_live
PROFILE=ltf_5m               # ltf_5m or ltf_15m
SYMBOL=ADAUSDT
LEVERAGE=3
```

See `.env.example` for all configurable parameters.

### 3. Run

```bash
python main.py
```

## Telegram Commands

| Command | Description |
|---------|-------------|
| `/start` | Resume bot (unpause) |
| `/stop` | Pause bot (no new entries, existing position unaffected) |
| `/status` | Show bot state, profile, exchange, position info |
| `/trades` | Show last 10 trades with PnL |
| `/kill` | Close open position at market and stop bot |
| `/shutdown` | Graceful shutdown after current cycle |
| `/ltf5m` | Switch to 5-minute profile |
| `/ltf15m` | Switch to 15-minute profile |
| `/demo` | Switch to Delta demo exchange |
| `/live` | Switch to CoinSwitch live exchange |

Profile and exchange switches are blocked while a position is open.

## Backtesting

```bash
python run_backtest.py --start 2024-01-01 --end 2024-06-30
python run_backtest.py --start 2024-01-01 --end 2024-06-30 --profile ltf_15m --output reports/
```

- Bar-by-bar replay with no lookahead bias
- Outputs: win rate, gross/net PnL, max drawdown, session breakdown
- Results saved to console, text file, and SQLite

## Deployment (AWS/VPS)

See [AWS_SETUP.md](AWS_SETUP.md) for full deployment guide using systemd.

Quick version:

```bash
# On server
sudo cp ops/swing_bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable swingbot
sudo systemctl start swingbot
```

## Tech Stack

- **Python 3.11+**
- **pandas** — candle data and HTF aggregation
- **numpy** — technical calculations
- **requests** — exchange and Telegram APIs
- **SQLite** — trade persistence and event logging

## License

This project is for personal/educational use.
