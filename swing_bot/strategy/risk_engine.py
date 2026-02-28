"""
Risk and Position Sizing Engine.
Fixed capital mode only (v1).

Formulas:
  sizing_balance_inr = FIXED_CAPITAL_INR (1000)
  risk_budget_usdt   = sizing_balance * leverage * (risk_pct / 100)
  sl_distance        = abs(entry - stop_loss)
  qty (Delta)        = floor(risk_budget / sl_distance), min 1
  qty (CoinSwitch)   = risk_budget / sl_distance
  notional           = entry * qty
  margin             = notional / leverage
  est_fee            = notional * (effective_cost_percent / 100)
"""

import logging
import math
from dataclasses import dataclass

from config.settings import Config

logger = logging.getLogger(__name__)

# INR/USDT approximate conversion (used only for sizing balance conversion)
# In v1 we treat 1000 INR as ~12 USDT at ~83 INR/USDT.
# This is updated at startup and stored in config if needed.
# For now use a reasonable default; operator can override via env.
INR_TO_USDT_RATE = 0.012  # 1 INR ≈ 0.012 USDT (i.e. ~83 INR per USDT)


@dataclass
class SizingResult:
    sizing_balance_inr: float
    sizing_balance_usdt: float
    risk_budget_usdt: float
    sl_distance: float
    quantity: float
    notional_usdt: float
    margin_usdt: float
    est_fee_usdt: float
    leverage: int
    sizing_mode: str            # always 'fixed_capital' in v1


def compute_sizing(
    cfg: Config,
    entry_price: float,
    stop_loss: float,
) -> SizingResult:
    """
    Compute position sizing for a trade.

    Parameters
    ----------
    cfg         : loaded Config
    entry_price : planned entry price (USDT)
    stop_loss   : planned stop loss price (USDT)

    Returns
    -------
    SizingResult with all fields populated.

    Raises
    ------
    ValueError if sl_distance <= 0
    """
    sl_distance = abs(entry_price - stop_loss)
    if sl_distance <= 0:
        raise ValueError(f"sl_distance must be > 0, got {sl_distance}")

    sizing_balance_inr = cfg.fixed_capital_inr  # always 1000 in v1
    sizing_balance_usdt = sizing_balance_inr * INR_TO_USDT_RATE

    risk_budget_usdt = sizing_balance_usdt * cfg.leverage * (cfg.risk_per_trade_percent / 100.0)

    if cfg.exchange == "delta_demo":
        # Delta uses integer contracts (1 contract = 1 ADAUSDT)
        quantity = math.floor(risk_budget_usdt / sl_distance)
        quantity = max(quantity, 1)
    else:
        # CoinSwitch uses decimal quantity
        quantity = risk_budget_usdt / sl_distance

    notional_usdt = entry_price * quantity
    margin_usdt = notional_usdt / cfg.leverage
    est_fee_usdt = notional_usdt * (cfg.effective_fee_percent / 100.0)

    result = SizingResult(
        sizing_balance_inr=sizing_balance_inr,
        sizing_balance_usdt=round(sizing_balance_usdt, 4),
        risk_budget_usdt=round(risk_budget_usdt, 4),
        sl_distance=round(sl_distance, 6),
        quantity=round(quantity, 4),
        notional_usdt=round(notional_usdt, 4),
        margin_usdt=round(margin_usdt, 4),
        est_fee_usdt=round(est_fee_usdt, 4),
        leverage=cfg.leverage,
        sizing_mode="fixed_capital",
    )

    logger.debug(
        f"Sizing: qty={result.quantity} notional={result.notional_usdt} "
        f"margin={result.margin_usdt} risk_budget={result.risk_budget_usdt} "
        f"est_fee={result.est_fee_usdt}"
    )
    return result
