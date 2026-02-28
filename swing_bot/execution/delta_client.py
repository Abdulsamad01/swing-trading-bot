"""
Delta Exchange India adapter.
Supports demo (testnet) and live environments.

API docs: https://docs.delta.exchange/
Auth: HMAC-SHA256 signature on each request.
"""

import hashlib
import hmac
import logging
import time
from typing import Optional

import requests

from config.settings import Config
from execution.base import ExchangeAdapter, OrderResult, PositionInfo
from execution.retry import with_retry

logger = logging.getLogger(__name__)

DELTA_DEMO_BASE = "https://cdn-ind.testnet.deltaex.org"
DELTA_LIVE_BASE = "https://api.india.delta.exchange"

# Delta side mapping
SIDE_MAP = {
    "buy": "buy",
    "sell": "sell",
}

# Delta order type mapping
ORDER_TYPE_MARKET = "market_order"
ORDER_TYPE_LIMIT = "limit_order"
ORDER_TYPE_STOP = "stop_loss_order"


class DeltaClient(ExchangeAdapter):

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.api_key = cfg.delta_demo_api_key
        self.api_secret = cfg.delta_demo_api_secret
        self.base_url = DELTA_DEMO_BASE if cfg.exchange == "delta_demo" else DELTA_LIVE_BASE
        self._product_cache: dict[str, str] = {}

    # ------------------------------------------------------------------ auth

    def _sign(self, method: str, path: str, payload: str, timestamp: str) -> str:
        message = method + timestamp + path + payload
        return hmac.new(
            self.api_secret.encode(),
            message.encode(),
            hashlib.sha256,
        ).hexdigest()

    def _headers(self, method: str, path: str, payload: str = "") -> dict:
        timestamp = str(int(time.time()))
        signature = self._sign(method, path, payload, timestamp)
        return {
            "api-key": self.api_key,
            "timestamp": timestamp,
            "signature": signature,
            "Content-Type": "application/json",
        }

    def _get(self, path: str, params: dict = None) -> dict:
        import json
        url = self.base_url + path
        query = ""
        if params:
            from urllib.parse import urlencode
            query = "?" + urlencode(params)
        headers = self._headers("GET", path + query)
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, body: dict) -> dict:
        import json
        payload = json.dumps(body)
        headers = self._headers("POST", path, payload)
        url = self.base_url + path
        resp = requests.post(url, data=payload, headers=headers, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def _delete(self, path: str, body: dict = None) -> dict:
        import json
        payload = json.dumps(body) if body else ""
        headers = self._headers("DELETE", path, payload)
        url = self.base_url + path
        resp = requests.delete(url, data=payload, headers=headers, timeout=10)
        resp.raise_for_status()
        return resp.json()

    # ---------------------------------------------------------- product lookup

    def get_product_id(self, symbol: str) -> Optional[str]:
        if symbol in self._product_cache:
            return self._product_cache[symbol]
        try:
            data = self._get("/v2/products", params={"contract_type": "perpetual_futures"})
            for product in data.get("result", []):
                if product.get("symbol") == symbol:
                    pid = str(product["id"])
                    self._product_cache[symbol] = pid
                    return pid
            logger.error(f"Delta: product not found for symbol {symbol}")
            return None
        except Exception as e:
            logger.error(f"Delta: get_product_id failed: {e}")
            return None

    # ------------------------------------------------------------ leverage

    def set_leverage(self, symbol: str, leverage: int) -> bool:
        product_id = self.get_product_id(symbol)
        if not product_id:
            return False
        try:
            def _call():
                return self._post("/v2/orders/leverage", {
                    "product_id": int(product_id),
                    "leverage": leverage,
                })
            resp = with_retry(
                _call,
                max_retries=self.cfg.max_retries,
                base_delay=self.cfg.retry_base_delay_seconds,
                jitter_percent=self.cfg.retry_jitter_percent,
                label="delta.set_leverage",
            )
            if resp.get("success"):
                logger.info(f"Delta: leverage set to {leverage}x for {symbol}")
                return True
            logger.error(f"Delta: set_leverage failed: {resp}")
            return False
        except Exception as e:
            logger.error(f"Delta: set_leverage exception: {e}")
            return False

    # ------------------------------------------------------------ position

    def get_position(self, symbol: str) -> PositionInfo:
        product_id = self.get_product_id(symbol)
        try:
            def _call():
                return self._get("/v2/positions", params={"product_id": product_id})
            resp = with_retry(
                _call,
                max_retries=self.cfg.max_retries,
                base_delay=self.cfg.retry_base_delay_seconds,
                jitter_percent=self.cfg.retry_jitter_percent,
                label="delta.get_position",
            )
            result = resp.get("result", {})
            if not result or float(result.get("size", 0)) == 0:
                return PositionInfo(
                    symbol=symbol, direction="flat", size=0,
                    entry_price=0, unrealized_pnl=0, product_id=product_id,
                )
            size = float(result["size"])
            direction = "long" if size > 0 else "short"
            return PositionInfo(
                symbol=symbol,
                direction=direction,
                size=abs(size),
                entry_price=float(result.get("entry_price", 0)),
                unrealized_pnl=float(result.get("unrealized_pnl", 0)),
                product_id=product_id,
            )
        except Exception as e:
            logger.error(f"Delta: get_position failed: {e}")
            return PositionInfo(
                symbol=symbol, direction="flat", size=0,
                entry_price=0, unrealized_pnl=0,
            )

    # ------------------------------------------------------------ orders

    def place_market_order(
        self,
        symbol: str,
        direction: str,
        quantity: float,
        reduce_only: bool = False,
    ) -> OrderResult:
        product_id = self.get_product_id(symbol)
        if not product_id:
            return OrderResult(success=False, order_id=None, filled_price=None,
                               quantity=None, raw=None, error="product_id not found")
        body = {
            "product_id": int(product_id),
            "order_type": ORDER_TYPE_MARKET,
            "side": direction,
            "size": int(quantity),
            "reduce_only": reduce_only,
        }
        try:
            def _call():
                return self._post("/v2/orders", body)
            resp = with_retry(
                _call,
                max_retries=self.cfg.max_retries,
                base_delay=self.cfg.retry_base_delay_seconds,
                jitter_percent=self.cfg.retry_jitter_percent,
                label="delta.place_market_order",
            )
            if resp.get("success"):
                r = resp.get("result", {})
                return OrderResult(
                    success=True,
                    order_id=str(r.get("id", "")),
                    filled_price=float(r.get("average_fill_price") or 0) or None,
                    quantity=float(r.get("size", quantity)),
                    raw=r,
                )
            return OrderResult(success=False, order_id=None, filled_price=None,
                               quantity=None, raw=resp, error=str(resp.get("error", resp)))
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
        product_id = self.get_product_id(symbol)
        if not product_id:
            return OrderResult(success=False, order_id=None, filled_price=None,
                               quantity=None, raw=None, error="product_id not found")
        body = {
            "product_id": int(product_id),
            "order_type": ORDER_TYPE_STOP,
            "side": direction,
            "size": int(quantity),
            "stop_price": str(stop_price),
            "reduce_only": reduce_only,
        }
        try:
            def _call():
                return self._post("/v2/orders", body)
            resp = with_retry(
                _call,
                max_retries=self.cfg.max_retries,
                base_delay=self.cfg.retry_base_delay_seconds,
                jitter_percent=self.cfg.retry_jitter_percent,
                label="delta.place_stop_order",
            )
            if resp.get("success"):
                r = resp.get("result", {})
                return OrderResult(
                    success=True,
                    order_id=str(r.get("id", "")),
                    filled_price=None,
                    quantity=float(r.get("size", quantity)),
                    raw=r,
                )
            return OrderResult(success=False, order_id=None, filled_price=None,
                               quantity=None, raw=resp, error=str(resp.get("error", resp)))
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
        product_id = self.get_product_id(symbol)
        if not product_id:
            return OrderResult(success=False, order_id=None, filled_price=None,
                               quantity=None, raw=None, error="product_id not found")
        body = {
            "product_id": int(product_id),
            "order_type": ORDER_TYPE_LIMIT,
            "side": direction,
            "size": int(quantity),
            "limit_price": str(price),
            "reduce_only": reduce_only,
        }
        try:
            def _call():
                return self._post("/v2/orders", body)
            resp = with_retry(
                _call,
                max_retries=self.cfg.max_retries,
                base_delay=self.cfg.retry_base_delay_seconds,
                jitter_percent=self.cfg.retry_jitter_percent,
                label="delta.place_limit_order",
            )
            if resp.get("success"):
                r = resp.get("result", {})
                return OrderResult(
                    success=True,
                    order_id=str(r.get("id", "")),
                    filled_price=None,
                    quantity=float(r.get("size", quantity)),
                    raw=r,
                )
            return OrderResult(success=False, order_id=None, filled_price=None,
                               quantity=None, raw=resp, error=str(resp.get("error", resp)))
        except Exception as e:
            return OrderResult(success=False, order_id=None, filled_price=None,
                               quantity=None, raw=None, error=str(e))

    def cancel_order(self, symbol: str, order_id: str) -> bool:
        product_id = self.get_product_id(symbol)
        try:
            def _call():
                return self._delete(f"/v2/orders/{order_id}", {"product_id": int(product_id)})
            resp = with_retry(
                _call,
                max_retries=self.cfg.max_retries,
                base_delay=self.cfg.retry_base_delay_seconds,
                jitter_percent=self.cfg.retry_jitter_percent,
                label="delta.cancel_order",
            )
            return resp.get("success", False)
        except Exception as e:
            logger.error(f"Delta: cancel_order failed: {e}")
            return False

    def close_position(self, symbol: str) -> OrderResult:
        pos = self.get_position(symbol)
        if pos.direction == "flat" or pos.size == 0:
            return OrderResult(success=True, order_id=None, filled_price=None,
                               quantity=0, raw=None, error="no_open_position")
        close_side = "sell" if pos.direction == "long" else "buy"
        return self.place_market_order(symbol, close_side, pos.size, reduce_only=True)
