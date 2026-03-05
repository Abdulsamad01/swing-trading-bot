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
from decimal import Decimal

from config.settings import Config

logger = logging.getLogger(__name__)

# INR/USDT conversion rate is now configurable via INR_TO_USDT_RATE env var.
# Default: 0.012 (1 INR ≈ 0.012 USDT, i.e. ~83 INR per USDT)


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
    min_notional: float = 0.0,
) -> SizingResult:
    """
    Compute position sizing for a trade.

    Parameters
    ----------
    cfg          : loaded Config
    entry_price  : planned entry price (USDT)
    stop_loss    : planned stop loss price (USDT)
    min_notional : exchange minimum order notional in USDT (fetched live)

    Returns
    -------
    SizingResult with all fields populated.

    Raises
    ------
    ValueError if sl_distance <= 0 or if notional cannot meet minimum
    """
    sl_distance = abs(entry_price - stop_loss)
    if sl_distance <= 0:
        raise ValueError(f"sl_distance must be > 0, got {sl_distance}")

    sizing_balance_inr = cfg.fixed_capital_inr
    sizing_balance_usdt = sizing_balance_inr * cfg.inr_to_usdt_rate

    risk_budget_usdt = sizing_balance_usdt * cfg.leverage * (cfg.risk_per_trade_percent / 100.0)

    if cfg.exchange == "delta_demo":
        # Delta uses integer contracts (1 contract = 1 ADAUSDT)
        quantity = math.floor(risk_budget_usdt / sl_distance)
        quantity = max(quantity, 1)
    else:
        # CoinSwitch / Binance use decimal quantity
        d_budget = Decimal(str(risk_budget_usdt))
        d_sl = Decimal(str(sl_distance))
        quantity = float(d_budget / d_sl)

    notional_usdt = entry_price * quantity

    # Enforce exchange minimum notional — bump quantity up if needed, but cap at risk budget
    if min_notional > 0 and notional_usdt < min_notional and entry_price > 0:
        min_qty_for_notional = min_notional / entry_price
        if cfg.exchange == "delta_demo":
            min_qty_for_notional = math.ceil(min_qty_for_notional)
        allowed_qty = risk_budget_usdt / entry_price
        if cfg.exchange == "delta_demo":
            allowed_qty = math.ceil(allowed_qty)
        if min_qty_for_notional > allowed_qty:
            logger.warning(
                "Sizing: min notional requires qty %.4f but risk cap allows only %.4f "
                "(risk_budget_usdt=%.2f); capping to risk budget",
                min_qty_for_notional, allowed_qty, risk_budget_usdt,
            )
            min_qty_for_notional = allowed_qty
        if min_qty_for_notional > quantity:
            logger.info(
                "Sizing: bumping qty from %.4f to %.4f to meet min notional %.2f USDT (was %.2f)",
                quantity, min_qty_for_notional, min_notional, notional_usdt,
            )
            quantity = min_qty_for_notional
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
