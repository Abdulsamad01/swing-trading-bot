"""
Backtest runner CLI.

Usage:
  python run_backtest.py --start 2024-01-01 --end 2024-06-30
  python run_backtest.py --start 2024-01-01 --end 2024-06-30 --profile ltf_5m
  python run_backtest.py --start 2024-01-01 --end 2024-06-30 --profile ltf_15m --output reports/

Environment:
  .env file must be present (same as live bot).
  EXCHANGE and API keys are not used for backtesting — only strategy params matter.
"""

import argparse
import logging
import sys
from datetime import datetime, timezone

from config.settings import load_config
from backtest.historical_data import fetch_historical_candles
from backtest.engine import run_backtest
from backtest.report import format_report, save_report, persist_results
from storage.repository import Repository


def parse_args():
    parser = argparse.ArgumentParser(description="Run strategy backtest")
    parser.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="End date YYYY-MM-DD")
    parser.add_argument("--profile", default=None, help="ltf_5m | ltf_15m (overrides .env)")
    parser.add_argument("--output", default="reports", help="Directory for report files")
    parser.add_argument("--no-save", action="store_true", help="Skip saving to SQLite")
    return parser.parse_args()


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logger = logging.getLogger(__name__)

    args = parse_args()

    # Load config
    try:
        cfg = load_config()
    except ValueError as e:
        print(f"Config error: {e}")
        sys.exit(1)

    # Override profile if passed
    if args.profile:
        if args.profile not in ("ltf_5m", "ltf_15m"):
            print("--profile must be ltf_5m or ltf_15m")
            sys.exit(1)
        cfg.profile = args.profile
        cfg._derive_profile_params()

    # Parse dates
    try:
        start_dt = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end_dt = datetime.strptime(args.end, "%Y-%m-%d").replace(hour=23, minute=59, tzinfo=timezone.utc)
    except ValueError:
        print("Date format must be YYYY-MM-DD")
        sys.exit(1)

    if start_dt >= end_dt:
        print("--start must be before --end")
        sys.exit(1)

    logger.info(f"Profile: {cfg.profile} | LTF: {cfg.ltf_interval} | HTF: {cfg.htf_interval}")

    # Fetch historical LTF candles
    ltf_df = fetch_historical_candles(
        symbol=cfg.symbol,
        interval=cfg.ltf_interval,
        start_dt=start_dt,
        end_dt=end_dt,
    )

    if ltf_df.empty:
        logger.error("No historical data fetched. Exiting.")
        sys.exit(1)

    logger.info(f"Data loaded: {len(ltf_df)} LTF bars")

    # Run backtest
    result = run_backtest(cfg, ltf_df, args.start, args.end)

    # Print report to console
    report_text = format_report(result)
    print(report_text)

    # Save report to file
    report_path = save_report(result, args.output)
    logger.info(f"Report saved: {report_path}")

    # Persist to SQLite
    if not args.no_save:
        repo = Repository(cfg.sqlite_path)
        persist_results(result, repo)
        logger.info(f"Results saved to SQLite: {cfg.sqlite_path}")


if __name__ == "__main__":
    main()
