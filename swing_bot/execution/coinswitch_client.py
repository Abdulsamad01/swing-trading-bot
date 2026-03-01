"""
CoinSwitch Pro adapter (India live trading).
API docs: https://coinswitch.co/pro/api/docs

Auth: HMAC-SHA256 on each request.
CoinSwitch uses decimal quantities (not integer contracts).
"""

import hashlib
import hmac
import json
import logging
import time
from typing import Optional
from urllib.parse import urlencode

import requests

from config.settings import Config
from execution.base import ExchangeAdapter, OrderResult, OrderStatusInfo, PositionInfo
from execution.retry import with_retry

logger = logging.getLogger(__name__)

COINSWITCH_BASE = "https://coinswitch.co"


class CoinSwitchClient(ExchangeAdapter):

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.api_key = cfg.coinswitch_api_key
        self.api_secret = cfg.coinswitch_api_secret
        self.base_url = COINSWITCH_BASE

    # ------------------------------------------------------------------ auth

    def _sign(self, method: str, path: str, payload: str = "") -> str:
        epoch_time = str(int(time.time() * 1000))
        message = epoch_time + method + path + payload
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return epoch_time, signature

    def _headers(self, method: str, path: str, payload: str = "") -> dict:
        epoch_time, signature = self._sign(method, path, payload)
        return {
            "X-Auth-Apikey": self.api_key,
            "X-Auth-Epoch": epoch_time,
            "X-Auth-Signature": signature,
            "Content-Type": "application/json",
        }

    def _get(self, path: str, params: dict = None) -> dict:
        query = ""
        if params:
            query = "?" + urlencode(params)
        headers = self._headers("GET", path + query)
        url = self.base_url + path
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, body: dict) -> dict:
        payload = json.dumps(body, separators=(",", ":"))
        headers = self._headers("POST", path, payload)
        url = self.base_url + path
        resp = requests.post(url, data=payload, headers=headers, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def _delete(self, path: str, body: dict = None) -> dict:
        payload = json.dumps(body, separators=(",", ":")) if body else ""
        headers = self._headers("DELETE", path, payload)
        url = self.base_url + path
        resp = requests.delete(url, data=payload, headers=headers, timeout=10)
        resp.raise_for_status()
        return resp.json()

    # ---------------------------------------------------------- product lookup

    def get_product_id(self, symbol: str) -> Optional[str]:
        # CoinSwitch uses symbol strings directly (e.g. "ADAUSDT")
        return symbol

    # ------------------------------------------------------------ leverage

    def set_leverage(self, symbol: str, leverage: int) -> bool:
        try:
            def _call():
                return self._post("/pro/v1/futures/leverage", {
                    "symbol": symbol,
                    "leverage": leverage,
                })
            resp = with_retry(
                _call,
                max_retries=self.cfg.max_retries,
                base_delay=self.cfg.retry_base_delay_seconds,
                jitter_percent=self.cfg.retry_jitter_percent,
                label="coinswitch.set_leverage",
            )
            if resp.get("success"):
                logger.info(f"CoinSwitch: leverage set to {leverage}x for {symbol}")
                return True
            logger.error(f"CoinSwitch: set_leverage failed: {resp}")
            return False
        except Exception as e:
            logger.error(f"CoinSwitch: set_leverage exception: {e}")
            return False

    # ------------------------------------------------------------ position

    def get_position(self, symbol: str) -> Optional[PositionInfo]:
        try:
            def _call():
                return self._get("/pro/v1/futures/positions", {"symbol": symbol})
            resp = with_retry(
                _call,
                max_retries=self.cfg.max_retries,
                base_delay=self.cfg.retry_base_delay_seconds,
                jitter_percent=self.cfg.retry_jitter_percent,
                label="coinswitch.get_position",
            )
            data = resp.get("data", {})
            positions = data if isinstance(data, list) else [data]

            for pos in positions:
                if pos.get("symbol") == symbol:
                    size = float(pos.get("positionAmt", 0))
                    if size == 0:
                        break
                    direction = "long" if size > 0 else "short"
                    return PositionInfo(
                        symbol=symbol,
                        direction=direction,
                        size=abs(size),
                        entry_price=float(pos.get("entryPrice", 0)),
                        unrealized_pnl=float(pos.get("unRealizedProfit", 0)),
                    )

            return PositionInfo(
                symbol=symbol, direction="flat", size=0,
                entry_price=0, unrealized_pnl=0,
            )
        except Exception as e:
            logger.error(f"CoinSwitch: get_position failed: {e}")
            return None

    def get_order_status(self, symbol: str, order_id: str) -> OrderStatusInfo:
        try:
            def _call():
                return self._get("/pro/v1/futures/orders", {
                    "symbol": symbol,
                    "orderId": order_id,
                })
            resp = with_retry(
                _call,
                max_retries=self.cfg.max_retries,
                base_delay=self.cfg.retry_base_delay_seconds,
                jitter_percent=self.cfg.retry_jitter_percent,
                label="coinswitch.get_order_status",
            )
            data = resp.get("data", {})
            if isinstance(data, list):
                data = data[0] if data else {}
            state = data.get("status", "").upper()
            status_map = {
                "NEW": "open",
                "PARTIALLY_FILLED": "open",
                "FILLED": "filled",
                "CANCELED": "cancelled",
                "CANCELLED": "cancelled",
                "EXPIRED": "cancelled",
            }
            status = status_map.get(state, "unknown")
            fill_price = None
            if status == "filled":
                fill_price = float(data.get("avgPrice") or 0) or None
            return OrderStatusInfo(
                order_id=order_id,
                status=status,
                fill_price=fill_price,
                raw=data,
            )
        except Exception as e:
            logger.error(f"CoinSwitch: get_order_status failed: {e}")
            return OrderStatusInfo(order_id=order_id, status="unknown")

    # ------------------------------------------------------------ orders

    def place_market_order(
        self,
        symbol: str,
        direction: str,
        quantity: float,
        reduce_only: bool = False,
    ) -> OrderResult:
        body = {
            "symbol": symbol,
            "side": direction.upper(),
            "type": "MARKET",
            "quantity": str(round(quantity, 4)),
            "reduceOnly": reduce_only,
        }
        try:
            def _call():
                return self._post("/pro/v1/futures/orders", body)
            resp = with_retry(
                _call,
                max_retries=self.cfg.max_retries,
                base_delay=self.cfg.retry_base_delay_seconds,
                jitter_percent=self.cfg.retry_jitter_percent,
                label="coinswitch.place_market_order",
            )
            if resp.get("success"):
                r = resp.get("data", {})
                return OrderResult(
                    success=True,
                    order_id=str(r.get("orderId", "")),
                    filled_price=float(r.get("avgPrice") or 0) or None,
                    quantity=float(r.get("executedQty", quantity)),
                    raw=r,
                )
            return OrderResult(success=False, order_id=None, filled_price=None,
                               quantity=None, raw=resp, error=str(resp.get("msg", resp)))
        except Exception as e:
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
        body = {
            "symbol": symbol,
            "side": direction.upper(),
            "type": "STOP_MARKET",
            "stopPrice": str(round(stop_price, 6)),
            "quantity": str(round(quantity, 4)),
            "reduceOnly": reduce_only,
        }
        try:
            def _call():
                return self._post("/pro/v1/futures/orders", body)
            resp = with_retry(
                _call,
                max_retries=self.cfg.max_retries,
                base_delay=self.cfg.retry_base_delay_seconds,
                jitter_percent=self.cfg.retry_jitter_percent,
                label="coinswitch.place_stop_order",
            )
            if resp.get("success"):
                r = resp.get("data", {})
                return OrderResult(
                    success=True,
                    order_id=str(r.get("orderId", "")),
                    filled_price=None,
                    quantity=float(r.get("origQty", quantity)),
                    raw=r,
                )
            return OrderResult(success=False, order_id=None, filled_price=None,
                               quantity=None, raw=resp, error=str(resp.get("msg", resp)))
        except Exception as e:
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
        body = {
            "symbol": symbol,
            "side": direction.upper(),
            "type": "TAKE_PROFIT",
            "price": str(round(price, 6)),
            "stopPrice": str(round(price, 6)),
            "quantity": str(round(quantity, 4)),
            "reduceOnly": reduce_only,
        }
        try:
            def _call():
                return self._post("/pro/v1/futures/orders", body)
            resp = with_retry(
                _call,
                max_retries=self.cfg.max_retries,
                base_delay=self.cfg.retry_base_delay_seconds,
                jitter_percent=self.cfg.retry_jitter_percent,
                label="coinswitch.place_limit_order",
            )
            if resp.get("success"):
                r = resp.get("data", {})
                return OrderResult(
                    success=True,
                    order_id=str(r.get("orderId", "")),
                    filled_price=None,
                    quantity=float(r.get("origQty", quantity)),
                    raw=r,
                )
            return OrderResult(success=False, order_id=None, filled_price=None,
                               quantity=None, raw=resp, error=str(resp.get("msg", resp)))
        except Exception as e:
            return OrderResult(success=False, order_id=None, filled_price=None,
                               quantity=None, raw=None, error=str(e))

    def cancel_order(self, symbol: str, order_id: str) -> bool:
        try:
            def _call():
                return self._delete("/pro/v1/futures/orders", {
                    "symbol": symbol,
                    "orderId": order_id,
                })
            resp = with_retry(
                _call,
                max_retries=self.cfg.max_retries,
                base_delay=self.cfg.retry_base_delay_seconds,
                jitter_percent=self.cfg.retry_jitter_percent,
                label="coinswitch.cancel_order",
            )
            return resp.get("success", False)
        except Exception as e:
            logger.error(f"CoinSwitch: cancel_order failed: {e}")
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
