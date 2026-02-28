"""
Config loader and validator.
Loads all settings from environment variables / .env file.
Fails fast on missing or invalid values.
"""

import os
from dataclasses import dataclass, field
from typing import Optional
from dotenv import load_dotenv

load_dotenv()


def _get(key: str, default=None, required: bool = False) -> str:
    val = os.environ.get(key, default)
    if required and (val is None or val == ""):
        raise ValueError(f"Required config key missing: {key}")
    return val


def _getfloat(key: str, default: float = None, required: bool = False) -> float:
    val = _get(key, str(default) if default is not None else None, required=required)
    if val is None:
        return None
    try:
        return float(val)
    except ValueError:
        raise ValueError(f"Config key {key} must be a float, got: {val!r}")


def _getint(key: str, default: int = None, required: bool = False) -> int:
    val = _get(key, str(default) if default is not None else None, required=required)
    if val is None:
        return None
    try:
        return int(val)
    except ValueError:
        raise ValueError(f"Config key {key} must be an int, got: {val!r}")


def _getbool(key: str, default: bool = False) -> bool:
    val = _get(key, str(default)).strip().lower()
    return val in ("true", "1", "yes")


@dataclass
class Config:
    # --- Core ---
    environment: str = ""           # demo | live
    exchange: str = ""              # delta_demo | coinswitch_live
    market_type: str = "futures"
    symbol: str = "ADAUSDT"
    profile: str = ""               # ltf_5m | ltf_15m
    leverage: int = 3
    use_fixed_capital: bool = True
    fixed_capital_inr: float = 1000.0
    risk_per_trade_percent: float = 2.0

    # --- Session RR (UTC) ---
    london_peak_start_utc: str = "07:00"
    london_peak_end_utc: str = "10:00"
    overlap_start_utc: str = "13:00"
    overlap_end_utc: str = "16:00"
    ny_peak_start_utc: str = "17:00"
    ny_peak_end_utc: str = "20:00"
    rr_london: float = 2.0
    rr_overlap: float = 4.0
    rr_ny: float = 3.0
    session_only_trading: bool = True

    # --- Strategy ---
    entry_percent: float = 50.0
    pivot_left_bars: int = 5
    pivot_right_bars: int = 5
    atr_period: int = 14
    displacement_mult_5m: float = 1.8
    displacement_mult_15m: float = 1.5
    max_fvg_age_5m: int = 24
    max_fvg_age_15m: int = 20

    # --- Fees ---
    delta_maker_fee_percent: float = 0.05
    delta_taker_fee_percent: float = 0.02
    coinswitch_trading_fee_percent: float = 0.20
    coinswitch_tds_percent: float = 1.00
    coinswitch_total_cost_percent: float = 1.20

    # --- Data & Runtime ---
    data_source_primary: str = "exchange_futures"
    data_source_fallback: str = "binance_usdm_futures"
    candle_limit: int = 300
    candle_close_buffer_seconds: int = 5
    max_retries: int = 3
    retry_base_delay_seconds: float = 1.0
    retry_jitter_percent: float = 20.0

    # --- Secrets ---
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    delta_demo_api_key: str = ""
    delta_demo_api_secret: str = ""
    coinswitch_api_key: str = ""
    coinswitch_api_secret: str = ""

    # --- Storage ---
    sqlite_path: str = "swing_bot.db"
    log_level: str = "INFO"

    # --- Derived (set after init) ---
    ltf_interval: str = field(init=False, default="")
    htf_interval: str = field(init=False, default="")
    displacement_mult: float = field(init=False, default=0.0)
    max_fvg_age: int = field(init=False, default=0)
    cycle_seconds: int = field(init=False, default=0)

    def __post_init__(self):
        self._derive_profile_params()

    def _derive_profile_params(self):
        if self.profile == "ltf_5m":
            self.ltf_interval = "5m"
            self.htf_interval = "15m"
            self.displacement_mult = self.displacement_mult_5m
            self.max_fvg_age = self.max_fvg_age_5m
            self.cycle_seconds = 300
        elif self.profile == "ltf_15m":
            self.ltf_interval = "15m"
            self.htf_interval = "1h"
            self.displacement_mult = self.displacement_mult_15m
            self.max_fvg_age = self.max_fvg_age_15m
            self.cycle_seconds = 900

    @property
    def effective_fee_percent(self) -> float:
        """Return effective total cost percent based on active exchange."""
        if self.exchange == "delta_demo":
            return self.delta_taker_fee_percent * 2  # entry + exit taker
        return self.coinswitch_total_cost_percent


def load_config() -> Config:
    """Load and validate all config from environment."""

    environment = _get("ENVIRONMENT", required=True)
    if environment not in ("demo", "live"):
        raise ValueError(f"ENVIRONMENT must be 'demo' or 'live', got: {environment!r}")

    exchange = _get("EXCHANGE", required=True)
    if exchange not in ("delta_demo", "coinswitch_live"):
        raise ValueError(f"EXCHANGE must be 'delta_demo' or 'coinswitch_live', got: {exchange!r}")

    market_type = _get("MARKET_TYPE", "futures")
    if market_type != "futures":
        raise ValueError("MARKET_TYPE must be 'futures'")

    symbol = _get("SYMBOL", "ADAUSDT")
    if symbol != "ADAUSDT":
        raise ValueError("SYMBOL must be 'ADAUSDT' in v1")

    profile = _get("PROFILE", required=True)
    if profile not in ("ltf_5m", "ltf_15m"):
        raise ValueError(f"PROFILE must be 'ltf_5m' or 'ltf_15m', got: {profile!r}")

    leverage = _getint("LEVERAGE", 3)
    if leverage != 3:
        raise ValueError("LEVERAGE must be 3 in v1")

    use_fixed_capital = _getbool("USE_FIXED_CAPITAL", True)
    if not use_fixed_capital:
        raise ValueError("USE_FIXED_CAPITAL must be true in v1")

    fixed_capital_inr = _getfloat("FIXED_CAPITAL_INR", 1000.0)
    if fixed_capital_inr != 1000.0:
        raise ValueError("FIXED_CAPITAL_INR must be 1000 in v1")

    risk_per_trade_percent = _getfloat("RISK_PER_TRADE_PERCENT", 2.0)
    if risk_per_trade_percent <= 0:
        raise ValueError("RISK_PER_TRADE_PERCENT must be > 0")

    # Secrets validation
    telegram_bot_token = _get("TELEGRAM_BOT_TOKEN", required=True)
    telegram_chat_id = _get("TELEGRAM_CHAT_ID", required=True)

    delta_demo_api_key = _get("DELTA_DEMO_API_KEY", "")
    delta_demo_api_secret = _get("DELTA_DEMO_API_SECRET", "")
    coinswitch_api_key = _get("COINSWITCH_API_KEY", "")
    coinswitch_api_secret = _get("COINSWITCH_API_SECRET", "")

    if exchange == "delta_demo":
        if not delta_demo_api_key or not delta_demo_api_secret:
            raise ValueError("DELTA_DEMO_API_KEY and DELTA_DEMO_API_SECRET are required for delta_demo exchange")
    if exchange == "coinswitch_live":
        if not coinswitch_api_key or not coinswitch_api_secret:
            raise ValueError("COINSWITCH_API_KEY and COINSWITCH_API_SECRET are required for coinswitch_live exchange")

    sqlite_path = _get("SQLITE_PATH", "swing_bot.db")
    log_level = _get("LOG_LEVEL", "INFO")
    if log_level not in ("DEBUG", "INFO", "WARNING", "ERROR"):
        raise ValueError(f"LOG_LEVEL must be DEBUG/INFO/WARNING/ERROR, got: {log_level!r}")

    coinswitch_trading_fee = _getfloat("COINSWITCH_TRADING_FEE_PERCENT", 0.20)
    coinswitch_tds = _getfloat("COINSWITCH_TDS_PERCENT", 1.00)
    coinswitch_total = _getfloat("COINSWITCH_TOTAL_COST_PERCENT", 1.20)

    cfg = Config(
        environment=environment,
        exchange=exchange,
        market_type=market_type,
        symbol=symbol,
        profile=profile,
        leverage=leverage,
        use_fixed_capital=use_fixed_capital,
        fixed_capital_inr=fixed_capital_inr,
        risk_per_trade_percent=risk_per_trade_percent,
        london_peak_start_utc=_get("LONDON_PEAK_START_UTC", "07:00"),
        london_peak_end_utc=_get("LONDON_PEAK_END_UTC", "10:00"),
        overlap_start_utc=_get("OVERLAP_START_UTC", "13:00"),
        overlap_end_utc=_get("OVERLAP_END_UTC", "16:00"),
        ny_peak_start_utc=_get("NY_PEAK_START_UTC", "17:00"),
        ny_peak_end_utc=_get("NY_PEAK_END_UTC", "20:00"),
        rr_london=_getfloat("RR_LONDON", 2.0),
        rr_overlap=_getfloat("RR_OVERLAP", 4.0),
        rr_ny=_getfloat("RR_NY", 3.0),
        session_only_trading=_getbool("SESSION_ONLY_TRADING", True),
        entry_percent=_getfloat("ENTRY_PERCENT", 50.0),
        pivot_left_bars=_getint("PIVOT_LEFT_BARS", 5),
        pivot_right_bars=_getint("PIVOT_RIGHT_BARS", 5),
        atr_period=_getint("ATR_PERIOD", 14),
        displacement_mult_5m=_getfloat("DISPLACEMENT_MULT_5M", 1.8),
        displacement_mult_15m=_getfloat("DISPLACEMENT_MULT_15M", 1.5),
        max_fvg_age_5m=_getint("MAX_FVG_AGE_5M", 24),
        max_fvg_age_15m=_getint("MAX_FVG_AGE_15M", 20),
        delta_maker_fee_percent=_getfloat("DELTA_MAKER_FEE_PERCENT", 0.05),
        delta_taker_fee_percent=_getfloat("DELTA_TAKER_FEE_PERCENT", 0.02),
        coinswitch_trading_fee_percent=coinswitch_trading_fee,
        coinswitch_tds_percent=coinswitch_tds,
        coinswitch_total_cost_percent=coinswitch_total,
        data_source_primary=_get("DATA_SOURCE_PRIMARY", "exchange_futures"),
        data_source_fallback=_get("DATA_SOURCE_FALLBACK", "binance_usdm_futures"),
        candle_limit=_getint("CANDLE_LIMIT", 300),
        candle_close_buffer_seconds=_getint("CANDLE_CLOSE_BUFFER_SECONDS", 5),
        max_retries=_getint("MAX_RETRIES", 3),
        retry_base_delay_seconds=_getfloat("RETRY_BASE_DELAY_SECONDS", 1.0),
        retry_jitter_percent=_getfloat("RETRY_JITTER_PERCENT", 20.0),
        telegram_bot_token=telegram_bot_token,
        telegram_chat_id=telegram_chat_id,
        delta_demo_api_key=delta_demo_api_key,
        delta_demo_api_secret=delta_demo_api_secret,
        coinswitch_api_key=coinswitch_api_key,
        coinswitch_api_secret=coinswitch_api_secret,
        sqlite_path=sqlite_path,
        log_level=log_level,
    )
    return cfg
