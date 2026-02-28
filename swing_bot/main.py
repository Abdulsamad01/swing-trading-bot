"""
Entry point for the swing trading bot.
"""

import logging
import sys

from config.settings import load_config
from bot.core import TradingBot


def setup_logging(level: str):
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("swing_bot.log", encoding="utf-8"),
        ],
    )


def main():
    try:
        cfg = load_config()
    except ValueError as e:
        print(f"Config error: {e}")
        sys.exit(1)

    setup_logging(cfg.log_level)
    logger = logging.getLogger(__name__)
    logger.info("Configuration loaded successfully.")

    bot = TradingBot(cfg)
    try:
        bot.start()
    except KeyboardInterrupt:
        logger.info("Bot stopped by keyboard interrupt.")
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
