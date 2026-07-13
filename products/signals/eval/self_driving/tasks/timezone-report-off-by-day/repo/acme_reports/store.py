from datetime import datetime

from .models import Account, Order


class InMemoryStore:
    """Stand-in for the commerce database. All order timestamps are UTC."""

    def __init__(self) -> None:
        self._accounts: dict[str, Account] = {}
        self._orders: list[Order] = []

    def add_account(self, account: Account) -> None:
        self._accounts[account.id] = account

    def add_order(self, order: Order) -> None:
        self._orders.append(order)

    def accounts(self) -> list[Account]:
        return list(self._accounts.values())

    def orders_between(self, account_id: str, start: datetime, end: datetime) -> list[Order]:
        """Orders for the account with start <= placed_at < end."""
        return sorted(
            (order for order in self._orders if order.account_id == account_id and start <= order.placed_at < end),
            key=lambda order: order.placed_at,
        )
