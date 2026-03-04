"""
Binance USD-M Futures adapter.
Supports testnet (demo-fapi.binance.com) and live environments.

API docs: https://binance-docs.github.io/apidocs/futures/en/
Auth: HMAC-SHA256 signature on query string, X-MBX-APIKEY header.
"""

import hashlib
import hmac
import logging
import time
from typing import Optional
from urllib.parse import urlencode

import requests

from config.settings import Config
from execution.base import ExchangeAdapter, OrderResult, OrderStatusInfo, PositionInfo

logger = logging.getLogger(__name__)

# Binance order status → internal status
STATUS_MAP = {
    "NEW": "open",
    "PARTIALLY_FILLED": "open",
    "FILLED": "filled",
    "CANCELED": "cancelled",
    "CANCELLED": "cancelled",
    "EXPIRED": "cancelled",
    "REJECTED": "cancelled",
}


class BinanceClient(ExchangeAdapter):

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.api_key = cfg.binance_testnet_api_key
        self.api_secret = cfg.binance_testnet_api_secret
        self.base_url = cfg.binance_testnet_base_url

    # ------------------------------------------------------------------ auth

    def _sign(self, params: dict) -> dict:
        """Add timestamp and HMAC-SHA256 signature to params."""
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
        resp.raise_for_status()
        return resp.json()

    def _delete(self, path: str, params: dict) -> dict:
        params = self._sign(params)
        url = self.base_url + path
        resp = requests.delete(url, params=params, headers=self._headers(), timeout=10)
        resp.raise_for_status()
        return resp.json()

    # ---------------------------------------------------------- product lookup

    def get_product_id(self, symbol: str) -> Optional[str]:
        """Binance uses symbol directly (e.g. ADAUSDT). No product ID needed."""
        return symbol

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
            logger.error(f"Binance: get_order_status failed: {e}")
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
        params = {
            "symbol": symbol,
            "side": side,
            "type": "STOP_MARKET",
            "stopPrice": str(stop_price),
            "quantity": str(quantity),
        }
        if reduce_only:
            params["reduceOnly"] = "true"
        try:
            def _call():
                return self._post("/fapi/v1/order", params)
            resp = self._retry(_call, "binance.place_stop_order")
            order_id = str(resp.get("orderId", ""))
            return OrderResult(
                success=True,
                order_id=order_id,
                filled_price=None,
                quantity=float(resp.get("origQty", quantity)),
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
        params = {
            "symbol": symbol,
            "side": side,
            "type": "TAKE_PROFIT_MARKET",
            "stopPrice": str(price),
            "quantity": str(quantity),
        }
        if reduce_only:
            params["reduceOnly"] = "true"
        try:
            def _call():
                return self._post("/fapi/v1/order", params)
            resp = self._retry(_call, "binance.place_limit_order")
            order_id = str(resp.get("orderId", ""))
            return OrderResult(
                success=True,
                order_id=order_id,
                filled_price=None,
                quantity=float(resp.get("origQty", quantity)),
                raw=resp,
            )
        except (requests.RequestException, KeyError, ValueError) as e:
            return OrderResult(success=False, order_id=None, filled_price=None,
                               quantity=None, raw=None, error=str(e))

    def cancel_order(self, symbol: str, order_id: str) -> bool:
        try:
            def _call():
                return self._delete("/fapi/v1/order", {
                    "symbol": symbol,
                    "orderId": order_id,
                })
            resp = self._retry(_call, "binance.cancel_order")
            return resp.get("status") == "CANCELED"
        except (requests.RequestException, KeyError, ValueError) as e:
            logger.error(f"Binance: cancel_order failed: {e}")
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
