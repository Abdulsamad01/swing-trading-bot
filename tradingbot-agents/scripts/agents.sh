#!/bin/bash
# agents.sh — Agent switcher for ADA/XRP Trading Bot
# Usage: source scripts/agents.sh
#        Then type an agent name to switch

# Guard: must be sourced, not executed directly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    echo "Error: This script must be sourced: source scripts/agents.sh" >&2
    exit 1
fi

AGENTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/claude-code"

# ── Helper ───────────────────────────────────────────────────────────────────

safe_copy() {
    local src="$1"
    if cp "$src" ./CLAUDE.md 2>/dev/null; then
        return 0
    else
        echo "❌ Failed to copy $src to ./CLAUDE.md" >&2
        return 1
    fi
}

# ── Claude Code Agent Switcher ─────────────────────────────────────────────────

agent-backend() {
    safe_copy "$AGENTS_DIR/backend.md" && \
    echo "✅ Backend Execution Agent — Delta Exchange (ADAUSD) + CoinSwitch (ADAUSDT/XRPUSDT)"
}

agent-strategy() {
    safe_copy "$AGENTS_DIR/strategy.md" && \
    echo "✅ ICT/SMC Strategy Agent — ADA & XRP calibrated"
}

agent-data() {
    safe_copy "$AGENTS_DIR/data-engineering.md" && \
    echo "✅ Data Engineering Agent — Delta + CoinSwitch feeds"
}

agent-backtest() {
    safe_copy "$AGENTS_DIR/backtesting.md" && \
    echo "✅ Backtesting Agent — ADA/XRP specific validation"
}

agent-devops() {
    safe_copy "$AGENTS_DIR/devops.md" && \
    echo "✅ DevOps Agent — multi-instance deployment"
}

agent-ml() {
    safe_copy "$AGENTS_DIR/ml-model.md" && \
    echo "✅ ML Model Agent (V2) — ADA + XRP separate models"
}

agent-review() {
    safe_copy "$AGENTS_DIR/code-review.md" && \
    echo "✅ Code Review Agent — exchange-aware financial safety checks"
}

agent-monitor() {
    safe_copy "$AGENTS_DIR/monitoring.md" && \
    echo "✅ Monitoring Agent — Delta + CoinSwitch dashboards"
}

agent-current() {
    if [ -f ./CLAUDE.md ]; then
        echo "Active agent:"
        head -3 ./CLAUDE.md
    else
        echo "No CLAUDE.md in current directory. Run an agent-* command to activate one."
    fi
}

agent-list() {
    echo ""
    echo "🤖 Available Agents — ADA/XRP Trading Bot"
    echo "──────────────────────────────────────────"
    echo "  agent-backend    Backend execution engine (Delta + CoinSwitch)"
    echo "  agent-strategy   ICT/SMC logic (ADA + XRP calibrated)"
    echo "  agent-data       Data pipelines (Delta ADAUSD + CoinSwitch)"
    echo "  agent-backtest   Backtesting (ADA/XRP specific)"
    echo "  agent-devops     Infrastructure + deployment"
    echo "  agent-ml         ML signal filter V2 (after V1 profitable)"
    echo "  agent-review     Code review (exchange-aware)"
    echo "  agent-monitor    Monitoring + Grafana dashboards"
    echo ""
    echo "  agent-current    Show which agent is active"
    echo "  agent-list       Show this list"
    echo ""
    echo "Claude.ai Projects (paste contents into each project):"
    echo "  tradingbot-agents/claude-ai/01-project-manager.md"
    echo "  tradingbot-agents/claude-ai/02-system-architect.md"
    echo "  tradingbot-agents/claude-ai/03-ict-smc-strategy.md"
    echo "  tradingbot-agents/claude-ai/04-risk-manager.md"
    echo "  tradingbot-agents/claude-ai/05-quant-analyst.md"
    echo "  tradingbot-agents/claude-ai/06-security.md"
    echo "  tradingbot-agents/claude-ai/07-research.md"
    echo ""
}

echo "🤖 Trading Bot agents loaded. Type 'agent-list' to see all options."
