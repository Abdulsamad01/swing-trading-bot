"""
Market data fetcher.
Fetches futures OHLCV candles from:
  - Primary: Delta Exchange India (futures)
  - Fallback: Binance USD-M futures

Never uses spot data.
Returns pandas DataFrame with UTC-indexed candles.
"""

import logging
import time
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
import requests

from config.settings import Config
from execution.retry import with_retry

logger = logging.getLogger(__name__)

# Binance USD-M futures fallback
BINANCE_FUTURES_BASE = "https://fapi.binance.com"

# Delta interval map
DELTA_INTERVAL_MAP = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "1h": "1h",
    "4h": "4h",
    "1d": "1d",
}

# Binance interval map
BINANCE_INTERVAL_MAP = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "1h": "1h",
    "4h": "4h",
    "1d": "1d",
}


def _parse_delta_candles(raw: list) -> pd.DataFrame:
    """Parse Delta Exchange candle response into DataFrame."""
    rows = []
    for c in raw:
        rows.append({
            "timestamp_utc": pd.to_datetime(c["time"], unit="s", utc=True),
            "open": float(c["open"]),
            "high": float(c["high"]),
            "low": float(c["low"]),
            "close": float(c["close"]),
            "volume": float(c.get("volume", 0)),
            "source_market": "futures",
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.sort_values("timestamp_utc").reset_index(drop=True)
    return df


def _parse_binance_candles(raw: list) -> pd.DataFrame:
    """Parse Binance klines response into DataFrame."""
    rows = []
    for c in raw:
        rows.append({
            "timestamp_utc": pd.to_datetime(c[0], unit="ms", utc=True),
            "open": float(c[1]),
            "high": float(c[2]),
            "low": float(c[3]),
            "close": float(c[4]),
            "volume": float(c[5]),
            "source_market": "futures",
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.sort_values("timestamp_utc").reset_index(drop=True)
    return df


def fetch_delta_candles(
    cfg: Config,
    interval: str,
    limit: int = 300,
) -> Optional[pd.DataFrame]:
    """
    Fetch futures OHLCV candles from Delta Exchange India.
    Uses demo or live base URL based on exchange config.
    """
    base = cfg.delta_demo_base_url if cfg.exchange == "delta_demo" else cfg.delta_live_base_url
    delta_interval = DELTA_INTERVAL_MAP.get(interval)
    if not delta_interval:
        logger.error(f"Unsupported Delta interval: {interval}")
        return None

    # Delta uses product symbol — ADAUSDT perpetual
    symbol = cfg.symbol  # e.g. ADAUSDT

    url = f"{base}/v2/history/candles"
    params = {
        "resolution": delta_interval,
        "symbol": symbol,
        "limit": limit,
    }

    try:
        def _call():
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            return resp.json()

        data = with_retry(
            _call,
            max_retries=cfg.max_retries,
            base_delay=cfg.retry_base_delay_seconds,
            jitter_percent=cfg.retry_jitter_percent,
            label="delta.fetch_candles",
        )

        if not data.get("success"):
            logger.warning(f"Delta candles API returned success=false: {data}")
            return None

        result = data.get("result", [])
        if not result:
            logger.warning("Delta candles returned empty result")
            return None

        df = _parse_delta_candles(result)
        logger.debug(f"Delta candles fetched: {len(df)} bars [{interval}]")
        return df

    except Exception as e:
        logger.warning(f"Delta candle fetch failed after retries: {e}")
        return None


def fetch_binance_candles(
    cfg: Config,
    symbol: str,
    interval: str,
    limit: int = 300,
) -> Optional[pd.DataFrame]:
    """
    Fetch futures OHLCV candles from Binance USD-M futures.
    Used as fallback only. Never spot.
    """
    binance_interval = BINANCE_INTERVAL_MAP.get(interval)
    if not binance_interval:
        logger.error(f"Unsupported Binance interval: {interval}")
        return None

    url = f"{BINANCE_FUTURES_BASE}/fapi/v1/klines"
    params = {
        "symbol": symbol,
        "interval": binance_interval,
        "limit": limit,
    }

    try:
        def _call():
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            return resp.json()

        raw = with_retry(
            _call,
            max_retries=cfg.max_retries,
            base_delay=cfg.retry_base_delay_seconds,
            jitter_percent=cfg.retry_jitter_percent,
            label="binance.fetch_candles",
        )

        if not raw:
            logger.warning("Binance futures candles returned empty")
            return None

        df = _parse_binance_candles(raw)
        logger.debug(f"Binance futures candles fetched: {len(df)} bars [{interval}]")
        return df

    except Exception as e:
        logger.warning(f"Binance fallback candle fetch failed after retries: {e}")
        return None


def fetch_candles(cfg: Config, interval: str) -> Optional[pd.DataFrame]:
    """
    Fetch candles with primary -> fallback logic.
    Always futures. Never spot.
    When exchange is binance_testnet, use Binance as primary (testnet uses live market data).
    Logs a warning in events if fallback is used.
    """
    limit = cfg.candle_limit

    if cfg.exchange == "binance_testnet":
        # Binance testnet: use Binance live market data as primary
        df = fetch_binance_candles(cfg, cfg.symbol, interval, limit)
        if df is not None and not df.empty:
            return df

        # Fallback: Delta Exchange India
        logger.warning(
            f"Binance primary data source failed for {interval}. Falling back to Delta."
        )
        df = fetch_delta_candles(cfg, interval, limit)
        if df is not None and not df.empty:
            return df
    else:
        # Default: Delta Exchange India as primary
        df = fetch_delta_candles(cfg, interval, limit)
        if df is not None and not df.empty:
            return df

        # Fallback: Binance USD-M futures
        logger.warning(
            f"Primary data source failed for {interval}. Falling back to Binance USD-M futures."
        )
        df = fetch_binance_candles(cfg, cfg.symbol, interval, limit)
        if df is not None and not df.empty:
            return df

    logger.error(f"Both primary and fallback data sources failed for {interval}.")
    return None


def build_htf_candles(ltf_df: pd.DataFrame, htf_interval: str) -> pd.DataFrame:
    """
    Aggregate LTF candles into HTF candles.
    Used when exchange does not return HTF data directly.
    """
    interval_map = {
        "15m": "15min",
        "1h": "1h",
        "4h": "4h",
        "1d": "1D",
    }
    rule = interval_map.get(htf_interval)
    if not rule:
        raise ValueError(f"Unsupported HTF interval for aggregation: {htf_interval}")

    df = ltf_df.set_index("timestamp_utc")
    htf = df.resample(rule, label="right", closed="right").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    ).dropna()
    htf["source_market"] = "futures"
    htf = htf.reset_index()
    htf = htf.rename(columns={"timestamp_utc": "timestamp_utc"})
    return htf
