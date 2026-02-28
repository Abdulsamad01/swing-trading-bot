"""
Backtest report generator.
Prints summary to console and saves to a text file.
Also persists results to SQLite via the repository.
"""

import os
from datetime import datetime, timezone
from typing import Optional

from backtest.engine import BacktestResult, BacktestTrade
from storage.repository import Repository


def _bar(label: str, value: str, width: int = 40) -> str:
    return f"  {label:<{width}} {value}"


def format_report(result: BacktestResult) -> str:
    sep = "=" * 58
    lines = [
        sep,
        f"  BACKTEST REPORT",
        f"  Run ID  : {result.run_id}",
        f"  Profile : {result.profile}",
        f"  Symbol  : {result.symbol}",
        f"  Period  : {result.start_date}  →  {result.end_date}",
        sep,
        "",
        "  TRADE SUMMARY",
        _bar("Total trades:", str(result.total_trades)),
        _bar("Winning trades:", f"{result.winning_trades}"),
        _bar("Losing trades:", f"{result.losing_trades}"),
        _bar("Win rate:", f"{result.win_rate:.1f}%"),
        "",
        "  PnL SUMMARY (USDT)",
        _bar("Gross PnL:", f"${result.gross_pnl_usdt:+.4f}"),
        _bar("Total fees:", f"${result.total_fees_usdt:.4f}"),
        _bar("Net PnL:", f"${result.net_pnl_usdt:+.4f}"),
        "",
        "  RISK METRICS",
        _bar("Max drawdown:", f"${result.max_drawdown_usdt:.4f}"),
        _bar("Best trade:", f"${result.best_trade_usdt:+.4f}"),
        _bar("Worst trade:", f"${result.worst_trade_usdt:+.4f}"),
        _bar("Avg RR ratio:", f"1:{result.avg_rr:.2f}"),
        "",
    ]

    if result.trades:
        # Session breakdown
        sessions = {}
        for t in result.trades:
            s = t.session
            if s not in sessions:
                sessions[s] = {"count": 0, "net": 0.0, "wins": 0}
            sessions[s]["count"] += 1
            sessions[s]["net"] += t.net_pnl_usdt
            if t.net_pnl_usdt > 0:
                sessions[s]["wins"] += 1

        lines.append("  SESSION BREAKDOWN")
        for s, data in sorted(sessions.items()):
            wr = data["wins"] / data["count"] * 100 if data["count"] else 0
            lines.append(
                _bar(
                    f"  {s.upper()}:",
                    f"{data['count']} trades | WR {wr:.0f}% | net ${data['net']:+.4f}",
                )
            )
        lines.append("")

        # Exit reason breakdown
        reasons = {}
        for t in result.trades:
            r = t.exit_reason
            reasons[r] = reasons.get(r, 0) + 1
        lines.append("  EXIT REASONS")
        for r, count in sorted(reasons.items()):
            lines.append(_bar(f"  {r}:", str(count)))
        lines.append("")

        # Trade log (last 20)
        lines.append("  TRADE LOG (most recent 20)")
        lines.append(
            f"  {'#':<4} {'Date':<18} {'Dir':<6} {'Entry':>8} {'Exit':>8} "
            f"{'SL':>8} {'TP':>8} {'Net PnL':>10} {'Reason':<14}"
        )
        lines.append("  " + "-" * 90)
        shown = result.trades[-20:]
        for idx, t in enumerate(shown, 1):
            dt_str = t.timestamp_utc.strftime("%Y-%m-%d %H:%M") if hasattr(t.timestamp_utc, "strftime") else str(t.timestamp_utc)[:16]
            pnl_str = f"${t.net_pnl_usdt:+.4f}"
            lines.append(
                f"  {idx:<4} {dt_str:<18} {t.direction.upper():<6} "
                f"{t.entry_price:>8.5f} {t.exit_price:>8.5f} "
                f"{t.stop_loss:>8.5f} {t.take_profit:>8.5f} "
                f"{pnl_str:>10} {t.exit_reason:<14}"
            )

    lines.append("")
    lines.append(sep)
    return "\n".join(lines)


def save_report(result: BacktestResult, output_dir: str = ".") -> str:
    """Save report to a text file. Returns the file path."""
    os.makedirs(output_dir, exist_ok=True)
    filename = f"backtest_{result.run_id}_{result.profile}_{result.start_date}_{result.end_date}.txt"
    filepath = os.path.join(output_dir, filename)
    report_text = format_report(result)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(report_text)
    return filepath


def persist_results(result: BacktestResult, repo: Repository):
    """Save backtest run and all trades to SQLite."""
    run_row = {
        "run_id": result.run_id,
        "profile": result.profile,
        "symbol": result.symbol,
        "start_date": result.start_date,
        "end_date": result.end_date,
        "total_trades": result.total_trades,
        "winning_trades": result.winning_trades,
        "losing_trades": result.losing_trades,
        "win_rate": result.win_rate,
        "gross_pnl_usdt": result.gross_pnl_usdt,
        "total_fees_usdt": result.total_fees_usdt,
        "net_pnl_usdt": result.net_pnl_usdt,
        "max_drawdown_usdt": result.max_drawdown_usdt,
        "best_trade_usdt": result.best_trade_usdt,
        "worst_trade_usdt": result.worst_trade_usdt,
        "avg_rr": result.avg_rr,
    }
    repo.insert_backtest_run(run_row)

    for t in result.trades:
        trade_row = {
            "run_id": result.run_id,
            "bar_index": t.bar_index,
            "timestamp_utc": t.timestamp_utc.isoformat() if hasattr(t.timestamp_utc, "isoformat") else str(t.timestamp_utc),
            "direction": t.direction,
            "entry_price": t.entry_price,
            "exit_price": t.exit_price,
            "stop_loss": t.stop_loss,
            "take_profit": t.take_profit,
            "quantity": t.quantity,
            "notional_usdt": t.notional_usdt,
            "risk_budget_usdt": t.risk_budget_usdt,
            "rr_ratio": t.rr_ratio,
            "gross_pnl_usdt": t.gross_pnl_usdt,
            "fees_usdt": t.fees_usdt,
            "net_pnl_usdt": t.net_pnl_usdt,
            "exit_reason": t.exit_reason,
            "bars_held": t.bars_held,
            "session": t.session,
        }
        repo.insert_backtest_trade(trade_row)
