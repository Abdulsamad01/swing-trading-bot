# TradingBot Agents — ADA/XRP ICT/SMC System

Complete agent setup for your ADA and XRP trading bot running on
**Delta Exchange** (validation) and **CoinSwitch Pro** (live).

---

## Quick Setup

### Step 1 — Copy agents into your trading bot project

```bash
cp -r tradingbot-agents/claude-ai/ /path/to/your/tradingbot/tradingbot-agents/claude-ai/
cp -r tradingbot-agents/claude-code/ /path/to/your/tradingbot/tradingbot-agents/claude-code/
cp scripts/agents.sh /path/to/your/tradingbot/scripts/
cp config/.env.example /path/to/your/tradingbot/config/
```

### Step 2 — Load the agent switcher

```bash
cd /path/to/your/tradingbot
source scripts/agents.sh
agent-list   # see all available agents
```

### Step 3 — Set up Claude.ai Projects (7 agents)

For each file in `tradingbot-agents/claude-ai/`:

1. Go to **claude.ai → Projects → New Project**
2. Name it exactly as shown below
3. Paste the entire file contents as the **System Prompt**

| File | Project Name |
|------|-------------|
| 01-project-manager.md | PM — Trading Bot |
| 02-system-architect.md | Architect — Trading Bot |
| 03-ict-smc-strategy.md | Strategy — ICT/SMC |
| 04-risk-manager.md | Risk Manager — Trading Bot |
| 05-quant-analyst.md | Quant — Trading Bot |
| 06-security.md | Security — Trading Bot |
| 07-research.md | Research — Trading Bot |

### Step 4 — Configure your .env files

```bash
# Delta Exchange (ADA validation)
cp config/.env.example config/delta.env
# Edit delta.env: set EXCHANGE=delta_demo, DEMO_SYMBOL=XRPUSD, ENVIRONMENT=demo

# CoinSwitch ADA (live)
cp config/.env.example config/coinswitch-ada.env
# Edit: set EXCHANGE=coinswitch_live, LIVE_SYMBOL=ADAUSDT, ENVIRONMENT=live

# CoinSwitch XRP (live)
cp config/.env.example config/coinswitch-xrp.env
# Edit: set EXCHANGE=coinswitch_live, LIVE_SYMBOL=XRPUSDT, ENVIRONMENT=live
```

---

## Agent Usage

### In Claude Code (terminal)

```bash
# Switch agent based on what you're working on
agent-strategy   # Writing OB/FVG/liquidity detection code
agent-backend    # Working on order execution or exchange connectors
agent-data       # Building data pipelines for Delta or CoinSwitch
agent-backtest   # Validating ADA or XRP strategy performance
agent-review     # Reviewing a PR before merge
agent-ml         # V2 ML work (only after V1 profitable 3+ months)
```

### In Claude.ai Projects

Open the relevant project and start chatting — the system prompt handles the context:

- **PM** → planning features, sprint breakdown, Delta→CoinSwitch decision gates
- **Architect** → system design, exchange adapter design, V2 planning
- **Strategy** → ICT/SMC concept to code translation, ADA/XRP specific rules
- **Risk Manager** → position sizing, drawdown limits, funding rate impact
- **Quant** → backtest validation, statistical significance checks
- **Security** → API key management, exchange security, code audits
- **Research** → new setup ideas, kill/continue research decisions

### In Antigravity (with awesome-skills installed)

Combine your CLAUDE.md with Antigravity skills:

```text
# After running: agent-strategy
@senior-architect review the market structure detection for XRP
@test-driven-development write tests for ADA order block detection
@python-patterns refactor the funding rate logging module
```

---

## Exchange Reference

| | Delta Exchange | CoinSwitch Pro |
|---|---|---|
| Purpose | ADA Validation | ADA + XRP Live |
| ADA Pair | ADAUSD | ADAUSDT |
| XRP Pair | N/A | XRPUSDT |
| Margin Type | Inverse (USD) | Linear (USDT) |
| Position Sizing | Complex (inverse formula) | Simple (USDT / risk_per_unit) |

---

## Deployment Flow

```text
Backtest (ADA/XRP data)
    ↓
Delta Exchange — ADAUSD live validation (min 2 weeks)
    ↓
CoinSwitch ADAUSDT — small size (10% of normal)
    ↓
CoinSwitch ADAUSDT — full size
    ↓ (same flow for XRP, CoinSwitch only)
CoinSwitch XRPUSDT — small → full
```
