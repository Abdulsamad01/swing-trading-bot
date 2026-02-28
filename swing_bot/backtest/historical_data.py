"""
Historical data fetcher for backtesting.
Uses Binance USD-M futures (fapi) as the source — it has deep history.
Never uses spot data.
"""

import logging
import time
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)

BINANCE_FUTURES_BASE = "https://fapi.binance.com"
MAX_BARS_PER_REQUEST = 1500  # Binance limit per call


def fetch_historical_candles(
    symbol: str,
    interval: str,
    start_dt: datetime,
    end_dt: datetime,
) -> pd.DataFrame:
    """
    Fetch full historical OHLCV from Binance USD-M futures for a date range.
    Paginates automatically until end_dt is reached.

    Parameters
    ----------
    symbol    : e.g. 'ADAUSDT'
    interval  : '5m', '15m', '1h', etc.
    start_dt  : start datetime (UTC-aware)
    end_dt    : end datetime (UTC-aware)

    Returns
    -------
    DataFrame with columns: timestamp_utc, open, high, low, close, volume, source_market
    Sorted ascending by timestamp_utc.
    """
    all_rows = []
    start_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)
    current_ms = start_ms

    logger.info(
        f"Fetching historical candles: {symbol} {interval} "
        f"{start_dt.strftime('%Y-%m-%d')} → {end_dt.strftime('%Y-%m-%d')}"
    )

    while current_ms < end_ms:
        params = {
            "symbol": symbol,
            "interval": interval,
            "startTime": current_ms,
            "endTime": end_ms,
            "limit": MAX_BARS_PER_REQUEST,
        }
        try:
            resp = requests.get(
                f"{BINANCE_FUTURES_BASE}/fapi/v1/klines",
                params=params,
                timeout=15,
            )
            resp.raise_for_status()
            raw = resp.json()
        except Exception as e:
            logger.error(f"Binance historical fetch error: {e}")
            break

        if not raw:
            break

        for c in raw:
            all_rows.append({
                "timestamp_utc": pd.to_datetime(c[0], unit="ms", utc=True),
                "open": float(c[1]),
                "high": float(c[2]),
                "low": float(c[3]),
                "close": float(c[4]),
                "volume": float(c[5]),
                "source_market": "futures",
            })

        last_ts = raw[-1][0]
        if last_ts >= end_ms or len(raw) < MAX_BARS_PER_REQUEST:
            break

        current_ms = last_ts + 1
        time.sleep(0.2)  # Respect Binance rate limits

    if not all_rows:
        logger.warning("No historical candles fetched.")
        return pd.DataFrame()

    df = pd.DataFrame(all_rows)
    df = df.drop_duplicates("timestamp_utc").sort_values("timestamp_utc").reset_index(drop=True)
    logger.info(f"Fetched {len(df)} candles for {symbol} {interval}")
    return df
