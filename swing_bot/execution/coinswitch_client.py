"""
CoinSwitch Pro adapter (India futures trading).
API docs: https://api-trading.coinswitch.co/

Auth: ED25519 signature on each request.
  - GET:    sign(METHOD + path_with_query + epoch_ms)
  - POST/DELETE: sign(METHOD + path + epoch_ms)

Confirmed endpoints (via API probing):
  - Ticker:      GET    /trade/api/v2/futures/ticker?symbol=ADAUSDT&exchange=exchange_2
  - Leverage:    POST   /trade/api/v2/futures/leverage
  - Positions:   GET    /trade/api/v2/futures/positions?exchange=exchange_2
  - Place order: POST   /trade/api/v2/futures/order
  - Order status:GET    /trade/api/v2/futures/order?order_id=...
  - Cancel:      DELETE /trade/api/v2/futures/order  (body: order_id + symbol + exchange)

Exchange param: "exchange_2" (for futures)
Symbol format for futures: "ADAUSDT" (no slash, unlike spot which uses "ADA/USDT")
Side: "BUY" / "SELL" (uppercase)
Order types: "LIMIT", "MARKET", "STOP_MARKET", "TAKE_PROFIT_MARKET" (uppercase)
Order type field: "order_type" (not "type")
Trigger price field: "trigger_price" (not "stopPrice")
Reduce only: "reduce_only" (snake_case boolean)
"""

import json
import logging
import time
from typing import Optional

import requests
from cryptography.hazmat.primitives.asymmetric import ed25519

from config.settings import Config
from execution.base import ExchangeAdapter, OrderResult, OrderStatusInfo, PositionInfo

logger = logging.getLogger(__name__)

COINSWITCH_BASE = "https://coinswitch.co"


def _to_futures_symbol(symbol: str) -> str:
    """Ensure symbol is in futures format: ADAUSDT (no slash)."""
    return symbol.upper().replace("/", "")


class CoinSwitchClient(ExchangeAdapter):

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.api_key = cfg.coinswitch_api_key
        self.api_secret = cfg.coinswitch_api_secret
        self.base_url = COINSWITCH_BASE
        self.futures_exchange = cfg.coinswitch_futures_exchange

    # ------------------------------------------------------------------ auth

    def _sign(self, method: str, path: str) -> tuple:
        """ED25519 signature: sign(METHOD + path + epoch_ms)."""
        epoch_time = str(int(time.time() * 1000))
        message = method + path + epoch_time
        secret_key_bytes = bytes.fromhex(self.api_secret)
        private_key = ed25519.Ed25519PrivateKey.from_private_bytes(secret_key_bytes)
        signature_bytes = private_key.sign(message.encode("utf-8"))
        return epoch_time, signature_bytes.hex()

    def _headers(self, method: str, path: str) -> dict:
        epoch_time, signature = self._sign(method, path)
        return {
            "X-AUTH-APIKEY": self.api_key,
            "X-AUTH-EPOCH": epoch_time,
            "X-AUTH-SIGNATURE": signature,
            "Content-Type": "application/json",
        }

    def _get(self, path: str, query_string: str = "") -> dict:
        """GET request. query_string should include leading '?' if non-empty."""
        full_path = path + query_string
        headers = self._headers("GET", full_path)
        url = self.base_url + full_path
        resp = requests.get(url, headers=headers, timeout=10)
        if not resp.ok:
            logger.error("CoinSwitch GET %s -> %s: %s", path, resp.status_code, resp.text[:500])
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, body: dict) -> dict:
        payload = json.dumps(body, separators=(",", ":"))
        headers = self._headers("POST", path)
        url = self.base_url + path
        resp = requests.post(url, data=payload, headers=headers, timeout=10)
        if not resp.ok:
            logger.error("CoinSwitch POST %s -> %s: %s", path, resp.status_code, resp.text[:500])
        resp.raise_for_status()
        return resp.json()

    def _delete(self, path: str, body: dict) -> dict:
        payload = json.dumps(body, separators=(",", ":"))
        headers = self._headers("DELETE", path)
        url = self.base_url + path
        resp = requests.delete(url, data=payload, headers=headers, timeout=10)
        if not resp.ok:
            logger.error("CoinSwitch DELETE %s -> %s: %s", path, resp.status_code, resp.text[:500])
        resp.raise_for_status()
        return resp.json()

    # ---------------------------------------------------------- helpers

    def _build_query(self, params: dict) -> str:
        """Build query string without URL-encoding slashes (CoinSwitch signs raw path)."""
        if not params:
            return ""
        parts = []
        for k, v in params.items():
            parts.append(f"{k}={v}")
        return "?" + "&".join(parts)

    # ---------------------------------------------------------- product lookup

    def get_product_id(self, symbol: str) -> Optional[str]:
        return _to_futures_symbol(symbol)

    def get_ticker_price(self, symbol: str) -> Optional[float]:
        fs = _to_futures_symbol(symbol)
        try:
            def _call():
                q = self._build_query({"symbol": fs, "exchange": self.futures_exchange})
                return self._get("/trade/api/v2/futures/ticker", q)
            resp = self._retry(_call, "coinswitch.get_ticker_price")
            data = resp.get("data", {})
            # Response: {"data": {"EXCHANGE_2": {"last_price": "0.2750", ...}}}
            ticker = data.get("EXCHANGE_2") or data.get(self.futures_exchange.upper()) or data
            if isinstance(ticker, dict):
                price = ticker.get("last_price") or ticker.get("lastPrice")
                return float(price) if price else None
            return None
        except Exception as e:
            logger.error("CoinSwitch: get_ticker_price failed: %s", e)
            return None

    def get_min_notional(self, symbol: str) -> float:
        # CoinSwitch minimum order is ~1100-1200 INR; convert to USDT
        return 1200.0 * self.cfg.inr_to_usdt_rate

    # ------------------------------------------------------------ leverage

    def set_leverage(self, symbol: str, leverage: int) -> bool:
        fs = _to_futures_symbol(symbol)
        try:
            def _call():
                return self._post("/trade/api/v2/futures/leverage", {
                    "symbol": fs,
                    "leverage": leverage,
                    "exchange": self.futures_exchange,
                })
            resp = self._retry(_call, "coinswitch.set_leverage")
            if resp.get("data"):
                logger.info(f"CoinSwitch: leverage set to {leverage}x for {fs}")
                return True
            logger.error(f"CoinSwitch: set_leverage failed: {resp}")
            return False
        except (requests.RequestException, KeyError, ValueError) as e:
            logger.error(f"CoinSwitch: set_leverage exception: {e}")
            return False

    # ------------------------------------------------------------ position

    def get_position(self, symbol: str) -> Optional[PositionInfo]:
        try:
            def _call():
                q = self._build_query({"exchange": self.futures_exchange})
                return self._get("/trade/api/v2/futures/positions", q)
            resp = self._retry(_call, "coinswitch.get_position")
            data = resp.get("data", {})

            # No open positions: {"message": "There are no open Positions"}
            if resp.get("message") and "no open" in resp["message"].lower():
                return PositionInfo(
                    symbol=symbol, direction="flat", size=0,
                    entry_price=0, unrealized_pnl=0,
                )

            positions = data if isinstance(data, list) else [data] if isinstance(data, dict) and data else []

            fs = _to_futures_symbol(symbol)
            for pos in positions:
                if not isinstance(pos, dict):
                    continue
                pos_sym = (pos.get("symbol") or "").upper()
                if pos_sym == fs:
                    size = float(pos.get("quantity") or pos.get("positionAmt") or 0)
                    if size == 0:
                        break
                    side = (pos.get("side") or "").upper()
                    direction = "long" if side == "BUY" else "short" if side == "SELL" else ("long" if size > 0 else "short")
                    return PositionInfo(
                        symbol=symbol,
                        direction=direction,
                        size=abs(size),
                        entry_price=float(pos.get("entry_price") or pos.get("entryPrice") or 0),
                        unrealized_pnl=float(pos.get("unrealised_pnl") or pos.get("pnl") or 0),
                    )

            return PositionInfo(
                symbol=symbol, direction="flat", size=0,
                entry_price=0, unrealized_pnl=0,
            )
        except (requests.RequestException, KeyError, ValueError) as e:
            logger.error(f"CoinSwitch: get_position failed: {e}")
            return None

    def get_order_status(self, symbol: str, order_id: str) -> OrderStatusInfo:
        try:
            def _call():
                q = self._build_query({"order_id": order_id})
                return self._get("/trade/api/v2/futures/order", q)
            resp = self._retry(_call, "coinswitch.get_order_status")
            data = resp.get("data", {})
            order_data = data.get("order", data)
            if order_data and order_data.get("order_id"):
                return self._parse_order_status(order_id, order_data)
        except (requests.RequestException, KeyError, ValueError) as e:
            logger.error(f"CoinSwitch: get_order_status failed: {e}")

        return OrderStatusInfo(order_id=order_id, status="unknown")

    def _parse_order_status(self, order_id: str, data: dict) -> OrderStatusInfo:
        state = (data.get("status") or "").upper()
        status_map = {
            "RAISED": "open",
            "USER_RAISED": "open",
            "NEW": "open",
            "PARTIALLY_FILLED": "open",
            "FILLED": "filled",
            "CANCELED": "cancelled",
            "CANCELLED": "cancelled",
            "USER_CANCELLED": "cancelled",
            "EXPIRED": "cancelled",
        }
        status = status_map.get(state, "unknown")
        fill_price = None
        if status == "filled":
            fill_price = float(data.get("avg_execution_price") or data.get("avg_exec_price") or data.get("price") or 0) or None
        return OrderStatusInfo(
            order_id=order_id,
            status=status,
            fill_price=fill_price,
            raw=data,
        )

    # ------------------------------------------------------------ orders

    def place_market_order(
        self,
        symbol: str,
        direction: str,
        quantity: float,
        reduce_only: bool = False,
    ) -> OrderResult:
        fs = _to_futures_symbol(symbol)
        body = {
            "symbol": fs,
            "side": direction.upper(),
            "order_type": "MARKET",
            "quantity": round(quantity, 4),
            "exchange": self.futures_exchange,
        }
        if reduce_only:
            body["reduce_only"] = True
        try:
            def _call():
                return self._post("/trade/api/v2/futures/order", body)
            resp = self._retry(_call, "coinswitch.place_market_order")
            data = resp.get("data", resp)
            order_id = str(data.get("order_id") or "")
            if order_id or resp.get("data"):
                return OrderResult(
                    success=True,
                    order_id=order_id,
                    filled_price=float(data.get("avg_execution_price") or data.get("price") or 0) or None,
                    quantity=float(data.get("exec_quantity") or data.get("quantity") or quantity),
                    raw=data,
                )
            return OrderResult(success=False, order_id=None, filled_price=None,
                               quantity=None, raw=resp,
                               error=str(resp.get("message") or resp))
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
        fs = _to_futures_symbol(symbol)
        body = {
            "symbol": fs,
            "side": direction.upper(),
            "order_type": "STOP_MARKET",
            "trigger_price": round(stop_price, 6),
            "quantity": round(quantity, 4),
            "exchange": self.futures_exchange,
            "reduce_only": reduce_only,
        }
        try:
            def _call():
                return self._post("/trade/api/v2/futures/order", body)
            resp = self._retry(_call, "coinswitch.place_stop_order")
            data = resp.get("data", resp)
            order_id = str(data.get("order_id") or "")
            if order_id or resp.get("data"):
                return OrderResult(
                    success=True,
                    order_id=order_id,
                    filled_price=None,
                    quantity=float(data.get("quantity") or quantity),
                    raw=data,
                )
            return OrderResult(success=False, order_id=None, filled_price=None,
                               quantity=None, raw=resp,
                               error=str(resp.get("message") or resp))
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
        fs = _to_futures_symbol(symbol)
        body = {
            "symbol": fs,
            "side": direction.upper(),
            "order_type": "TAKE_PROFIT_MARKET",
            "trigger_price": round(price, 6),
            "quantity": round(quantity, 4),
            "exchange": self.futures_exchange,
            "reduce_only": reduce_only,
        }
        try:
            def _call():
                return self._post("/trade/api/v2/futures/order", body)
            resp = self._retry(_call, "coinswitch.place_limit_order")
            data = resp.get("data", resp)
            order_id = str(data.get("order_id") or "")
            if order_id or resp.get("data"):
                return OrderResult(
                    success=True,
                    order_id=order_id,
                    filled_price=None,
                    quantity=float(data.get("quantity") or quantity),
                    raw=data,
                )
            return OrderResult(success=False, order_id=None, filled_price=None,
                               quantity=None, raw=resp,
                               error=str(resp.get("message") or resp))
        except (requests.RequestException, KeyError, ValueError) as e:
            return OrderResult(success=False, order_id=None, filled_price=None,
                               quantity=None, raw=None, error=str(e))

    def cancel_order(self, symbol: str, order_id: str) -> bool:
        fs = _to_futures_symbol(symbol)
        try:
            def _call():
                return self._delete("/trade/api/v2/futures/order", {
                    "order_id": order_id,
                    "symbol": fs,
                    "exchange": self.futures_exchange,
                })
            resp = self._retry(_call, "coinswitch.cancel_order")
            return resp.get("data") is not None
        except (requests.RequestException, KeyError, ValueError) as e:
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
        close_side = "SELL" if pos.direction == "long" else "BUY"
        return self.place_market_order(symbol, close_side, pos.size, reduce_only=True)
