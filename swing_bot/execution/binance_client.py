"""
Binance USD-M Futures adapter.
Supports testnet (demo-fapi.binance.com) and live environments.

API docs: https://binance-docs.github.io/apidocs/futures/en/
Auth: HMAC-SHA256 signature on query string, X-MBX-APIKEY header.
"""

import hashlib
import hmac
import logging
import math
import time
from typing import Optional
from urllib.parse import urlencode

import requests

from config.settings import Config
from execution.base import ExchangeAdapter, OrderResult, OrderStatusInfo, PositionInfo

logger = logging.getLogger(__name__)

# Binance regular order status -> internal status
STATUS_MAP = {
    "NEW": "open",
    "PARTIALLY_FILLED": "open",
    "FILLED": "filled",
    "CANCELED": "cancelled",
    "CANCELLED": "cancelled",
    "EXPIRED": "cancelled",
    "REJECTED": "cancelled",
}

# Binance algo order status -> internal status
ALGO_STATUS_MAP = {
    "NEW": "open",
    "TRIGGERING": "open",
    "TRIGGERED": "filled",
    "CANCELLED": "cancelled",
    "CANCELED": "cancelled",
    "EXPIRED": "cancelled",
    "REJECTED": "cancelled",
    "FINISHED": "filled",
}


class BinanceClient(ExchangeAdapter):

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.api_key = cfg.binance_testnet_api_key
        self.api_secret = cfg.binance_testnet_api_secret
        self.base_url = cfg.binance_testnet_base_url
        self._symbol_info: dict = {}  # cached lot-size / price precision per symbol

    # ------------------------------------------------------------------ auth

    def _sign(self, params: dict) -> dict:
        """Add timestamp and HMAC-SHA256 signature to a copy of params."""
        params = {k: v for k, v in params.items() if k not in ("timestamp", "signature")}
        params["timestamp"] = int(time.time() * 1000)
        query_string = urlencode(params)
        signature = hmac.new(
            self.api_secret.encode(),
            query_string.encode(),
            hashlib.sha256,
        ).hexdigest()
        params["signature"] = signature
        return params

    def _headers(self) -> dict:
        return {
            "X-MBX-APIKEY": self.api_key,
            "Content-Type": "application/x-www-form-urlencoded",
        }

    def _get(self, path: str, params: dict = None) -> dict:
        params = self._sign(params or {})
        url = self.base_url + path
        resp = requests.get(url, params=params, headers=self._headers(), timeout=10)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, params: dict) -> dict:
        params = self._sign(params)
        url = self.base_url + path
        resp = requests.post(url, data=urlencode(params), headers=self._headers(), timeout=10)
        if not resp.ok:
            logger.error("Binance POST %s -> %s: %s", path, resp.status_code, resp.text)
        resp.raise_for_status()
        return resp.json()

    def _delete(self, path: str, params: dict) -> dict:
        params = self._sign(params)
        url = self.base_url + path
        resp = requests.delete(url, params=params, headers=self._headers(), timeout=10)
        resp.raise_for_status()
        return resp.json()

    # ---------------------------------------------------------- symbol info

    def _load_symbol_info(self, symbol: str):
        """Fetch lot-size, price-precision, and min-notional from exchangeInfo and cache it."""
        if symbol in self._symbol_info:
            return
        try:
            url = self.base_url + "/fapi/v1/exchangeInfo"
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            for s in data.get("symbols", []):
                if s["symbol"] == symbol:
                    info = {"min_notional": 5.0}  # safe default
                    for f in s.get("filters", []):
                        if f["filterType"] == "LOT_SIZE":
                            step_size = float(f["stepSize"])
                            if step_size >= 1:
                                precision = 0
                            else:
                                precision = len(f["stepSize"].rstrip("0").split(".")[-1])
                            info["step_size"] = step_size
                            info["qty_precision"] = precision
                            info["min_qty"] = float(f["minQty"])
                        elif f["filterType"] == "MIN_NOTIONAL":
                            info["min_notional"] = float(f.get("notional", 5.0))
                        elif f["filterType"] == "PRICE_FILTER":
                            info["tick_size"] = float(f.get("tickSize", 0.000001))
                    if "step_size" in info:
                        self._symbol_info[symbol] = info
                        logger.info(
                            "Binance: loaded %s info: step=%s precision=%d min_qty=%s min_notional=%s",
                            symbol, info["step_size"], info["qty_precision"],
                            info["min_qty"], info["min_notional"],
                        )
                        return
            logger.warning("Binance: symbol %s not found in exchangeInfo", symbol)
        except Exception as e:
            logger.error("Binance: failed to load exchangeInfo: %s", e)

    def _round_quantity(self, symbol: str, quantity: float) -> float:
        """Round quantity to the symbol's lot-size step."""
        self._load_symbol_info(symbol)
        info = self._symbol_info.get(symbol)
        if info:
            step = info["step_size"]
            # Floor to step size to avoid exceeding risk budget
            quantity = math.floor(quantity / step) * step
            quantity = round(quantity, info["qty_precision"])
            quantity = max(quantity, info["min_qty"])
        return quantity

    def _round_price(self, symbol: str, price: float) -> float:
        """Round price to the symbol's tick size precision."""
        self._load_symbol_info(symbol)
        info = self._symbol_info.get(symbol)
        if info and "tick_size" in info:
            tick = info["tick_size"]
            if tick >= 1:
                return round(price)
            precision = len(str(tick).rstrip("0").split(".")[-1])
            return round(price, precision)
        return round(price, 4)

    # ---------------------------------------------------------- product lookup

    def get_product_id(self, symbol: str) -> Optional[str]:
        """Binance uses symbol directly (e.g. ADAUSDT). No product ID needed."""
        return symbol

    def get_ticker_price(self, symbol: str) -> Optional[float]:
        try:
            url = self.base_url + "/fapi/v1/ticker/price"
            resp = requests.get(url, params={"symbol": symbol}, timeout=10)
            resp.raise_for_status()
            return float(resp.json()["price"])
        except Exception as e:
            logger.error("Binance: get_ticker_price failed: %s", e)
            return None

    def get_min_notional(self, symbol: str) -> float:
        self._load_symbol_info(symbol)
        info = self._symbol_info.get(symbol)
        return info.get("min_notional", 5.0) if info else 5.0

    # ------------------------------------------------------------ leverage

    def set_leverage(self, symbol: str, leverage: int) -> bool:
        try:
            def _call():
                return self._post("/fapi/v1/leverage", {
                    "symbol": symbol,
                    "leverage": leverage,
                })
            resp = self._retry(_call, "binance.set_leverage")
            if resp.get("leverage") == leverage:
                logger.info(f"Binance: leverage set to {leverage}x for {symbol}")
                return True
            logger.info(f"Binance: leverage response: {resp}")
            return True  # Binance returns the new leverage value, accept any response
        except (requests.RequestException, KeyError, ValueError) as e:
            logger.error(f"Binance: set_leverage exception: {e}")
            return False

    # ------------------------------------------------------------ position

    def get_position(self, symbol: str) -> Optional[PositionInfo]:
        try:
            def _call():
                return self._get("/fapi/v2/positionRisk", {"symbol": symbol})
            resp = self._retry(_call, "binance.get_position")
            # resp is a list of position objects
            if not resp:
                return PositionInfo(
                    symbol=symbol, direction="flat", size=0,
                    entry_price=0, unrealized_pnl=0,
                )

            pos = resp[0] if isinstance(resp, list) else resp
            position_amt = float(pos.get("positionAmt", 0))

            if position_amt == 0:
                return PositionInfo(
                    symbol=symbol, direction="flat", size=0,
                    entry_price=0, unrealized_pnl=0,
                )

            direction = "long" if position_amt > 0 else "short"
            return PositionInfo(
                symbol=symbol,
                direction=direction,
                size=abs(position_amt),
                entry_price=float(pos.get("entryPrice", 0)),
                unrealized_pnl=float(pos.get("unRealizedProfit", 0)),
            )
        except (requests.RequestException, KeyError, ValueError) as e:
            logger.error(f"Binance: get_position failed: {e}")
            return None

    def get_order_status(self, symbol: str, order_id: str) -> OrderStatusInfo:
        """Query order status. Tries algo order first, falls back to regular order."""
        # Try algo order endpoint (SL/TP orders use algoId)
        try:
            resp = self._get("/fapi/v1/algoOrder", {"algoId": order_id})
            algo_status = resp.get("algoStatus", "")
            status = ALGO_STATUS_MAP.get(algo_status, "unknown")
            fill_price = None
            # When algo triggers, it creates an actual order with actualOrderId
            actual_order_id = resp.get("actualOrderId", "")
            if status == "filled" and actual_order_id:
                # Query the actual triggered order for fill price
                try:
                    def _actual_call():
                        return self._get("/fapi/v1/order", {
                            "symbol": symbol,
                            "orderId": actual_order_id,
                        })
                    actual_resp = self._retry(_actual_call, "binance.get_actual_order")
                    fill_price = float(actual_resp.get("avgPrice") or 0) or None
                except Exception:
                    fill_price = float(resp.get("actualPrice") or 0) or None
            return OrderStatusInfo(
                order_id=order_id,
                status=status,
                fill_price=fill_price,
                raw=resp,
            )
        except (requests.RequestException, KeyError, ValueError):
            pass  # Not an algo order, try regular endpoint

        # Fallback: regular order endpoint (entry orders, manual orders)
        try:
            def _call():
                return self._get("/fapi/v1/order", {
                    "symbol": symbol,
                    "orderId": order_id,
                })
            resp = self._retry(_call, "binance.get_order_status")
            raw_status = resp.get("status", "")
            status = STATUS_MAP.get(raw_status, "unknown")
            fill_price = None
            if status == "filled":
                fill_price = float(resp.get("avgPrice") or 0) or None
            return OrderStatusInfo(
                order_id=order_id,
                status=status,
                fill_price=fill_price,
                raw=resp,
            )
        except (requests.RequestException, KeyError, ValueError) as e:
            logger.error(f"Binance: get_order_status failed for {order_id}: {e}")
            return OrderStatusInfo(order_id=order_id, status="unknown")

    # ------------------------------------------------------------ orders

    def place_market_order(
        self,
        symbol: str,
        direction: str,
        quantity: float,
        reduce_only: bool = False,
    ) -> OrderResult:
        side = direction.upper()  # BUY or SELL
        quantity = self._round_quantity(symbol, quantity)
        params = {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": str(quantity),
        }
        if reduce_only:
            params["reduceOnly"] = "true"
        try:
            def _call():
                return self._post("/fapi/v1/order", params)
            resp = self._retry(_call, "binance.place_market_order")
            order_id = str(resp.get("orderId", ""))
            fill_price = float(resp.get("avgPrice") or 0) or None
            return OrderResult(
                success=True,
                order_id=order_id,
                filled_price=fill_price,
                quantity=float(resp.get("origQty", quantity)),
                raw=resp,
            )
        except (requests.RequestException, KeyError, ValueError) as e:
            return OrderResult(success=False, order_id=None, filled_price=None,
                               quantity=None, raw=None, error=str(e))

    def place_stop_order(
        self,
        symbol: str,
        direction: str,
        quantity: float,
        stop_price: float,
        reduce_only: bool = True,
    ) -> OrderResult:
        side = direction.upper()
        quantity = self._round_quantity(symbol, quantity)
        stop_price = self._round_price(symbol, stop_price)
        params = {
            "symbol": symbol,
            "side": side,
            "algoType": "CONDITIONAL",
            "type": "STOP_MARKET",
            "triggerPrice": str(stop_price),
            "quantity": str(quantity),
        }
        if reduce_only:
            params["reduceOnly"] = "true"
        try:
            def _call():
                return self._post("/fapi/v1/algoOrder", params)
            resp = self._retry(_call, "binance.place_stop_order")
            order_id = str(resp.get("algoId", ""))
            return OrderResult(
                success=True,
                order_id=order_id,
                filled_price=None,
                quantity=float(resp.get("quantity", quantity)),
                raw=resp,
            )
        except (requests.RequestException, KeyError, ValueError) as e:
            return OrderResult(success=False, order_id=None, filled_price=None,
                               quantity=None, raw=None, error=str(e))

    def place_limit_order(
        self,
        symbol: str,
        direction: str,
        quantity: float,
        price: float,
        reduce_only: bool = True,
    ) -> OrderResult:
        side = direction.upper()
        quantity = self._round_quantity(symbol, quantity)
        price = self._round_price(symbol, price)
        params = {
            "symbol": symbol,
            "side": side,
            "algoType": "CONDITIONAL",
            "type": "TAKE_PROFIT_MARKET",
            "triggerPrice": str(price),
            "quantity": str(quantity),
        }
        if reduce_only:
            params["reduceOnly"] = "true"
        try:
            def _call():
                return self._post("/fapi/v1/algoOrder", params)
            resp = self._retry(_call, "binance.place_limit_order")
            order_id = str(resp.get("algoId", ""))
            return OrderResult(
                success=True,
                order_id=order_id,
                filled_price=None,
                quantity=float(resp.get("quantity", quantity)),
                raw=resp,
            )
        except (requests.RequestException, KeyError, ValueError) as e:
            return OrderResult(success=False, order_id=None, filled_price=None,
                               quantity=None, raw=None, error=str(e))

    def cancel_order(self, symbol: str, order_id: str) -> bool:
        """Cancel an order. Tries algo order first, falls back to regular order."""
        # Try algo order cancel (SL/TP use algoId)
        try:
            resp = self._delete("/fapi/v1/algoOrder", {
                "symbol": symbol,
                "algoId": order_id,
            })
            if resp.get("code") == "200" or resp.get("msg") == "success":
                return True
        except (requests.RequestException, KeyError, ValueError):
            pass  # Not an algo order, try regular

        # Fallback: regular order cancel
        try:
            def _call():
                return self._delete("/fapi/v1/order", {
                    "symbol": symbol,
                    "orderId": order_id,
                })
            resp = self._retry(_call, "binance.cancel_order")
            return resp.get("status") == "CANCELED"
        except (requests.RequestException, KeyError, ValueError) as e:
            logger.error(f"Binance: cancel_order failed for {order_id}: {e}")
            return False

    def close_position(self, symbol: str) -> OrderResult:
        pos = self.get_position(symbol)
        if pos is None:
            return OrderResult(success=False, order_id=None, filled_price=None,
                               quantity=None, raw=None, error="position_query_failed")
        if pos.direction == "flat" or pos.size == 0:
            return OrderResult(success=True, order_id=None, filled_price=None,
                               quantity=0, raw=None, error="no_open_position")
        close_side = "sell" if pos.direction == "long" else "buy"
        return self.place_market_order(symbol, close_side, pos.size, reduce_only=True)
