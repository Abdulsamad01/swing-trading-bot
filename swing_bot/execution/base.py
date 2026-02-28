"""
Unified exchange adapter interface.
Both Delta and CoinSwitch clients implement this interface.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class OrderResult:
    success: bool
    order_id: Optional[str]
    filled_price: Optional[float]
    quantity: Optional[float]
    raw: Optional[dict]
    error: Optional[str] = None


@dataclass
class PositionInfo:
    symbol: str
    direction: str          # 'long' | 'short' | 'flat'
    size: float
    entry_price: float
    unrealized_pnl: float
    product_id: Optional[str] = None


class ExchangeAdapter(ABC):

    @abstractmethod
    def set_leverage(self, symbol: str, leverage: int) -> bool:
        """Set leverage for symbol. Returns True on success."""
        ...

    @abstractmethod
    def get_position(self, symbol: str) -> PositionInfo:
        """Return current position for symbol. Returns flat PositionInfo if none."""
        ...

    @abstractmethod
    def place_market_order(
        self,
        symbol: str,
        direction: str,
        quantity: float,
        reduce_only: bool = False,
    ) -> OrderResult:
        """Place market order. direction: 'buy' | 'sell'."""
        ...

    @abstractmethod
    def place_stop_order(
        self,
        symbol: str,
        direction: str,
        quantity: float,
        stop_price: float,
        reduce_only: bool = True,
    ) -> OrderResult:
        """Place stop-loss order."""
        ...

    @abstractmethod
    def place_limit_order(
        self,
        symbol: str,
        direction: str,
        quantity: float,
        price: float,
        reduce_only: bool = True,
    ) -> OrderResult:
        """Place limit take-profit order."""
        ...

    @abstractmethod
    def cancel_order(self, symbol: str, order_id: str) -> bool:
        """Cancel an order by ID. Returns True on success."""
        ...

    @abstractmethod
    def close_position(self, symbol: str) -> OrderResult:
        """Close entire open position for symbol at market."""
        ...

    @abstractmethod
    def get_product_id(self, symbol: str) -> Optional[str]:
        """Return exchange-specific product/contract ID for symbol."""
        ...
