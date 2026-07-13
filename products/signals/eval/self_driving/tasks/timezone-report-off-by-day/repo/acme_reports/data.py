from datetime import UTC, datetime

from .models import Account, Order
from .store import InMemoryStore


def sample_store() -> InMemoryStore:
    store = InMemoryStore()
    store.add_account(
        Account(id="acct_pdx", name="Bridge City Goods", email="ops@bridgecity.example", timezone="America/Los_Angeles")
    )
    store.add_account(
        Account(id="acct_ber", name="Kiez Kaffee", email="hallo@kiezkaffee.example", timezone="Europe/Berlin")
    )
    store.add_account(
        Account(id="acct_tyo", name="Shibuya Prints", email="store@shibuyaprints.example", timezone="Asia/Tokyo")
    )

    orders = [
        Order(id="o-1001", account_id="acct_pdx", total_cents=4200, placed_at=datetime(2026, 7, 9, 15, 12, tzinfo=UTC)),
        Order(id="o-1002", account_id="acct_pdx", total_cents=1850, placed_at=datetime(2026, 7, 9, 23, 41, tzinfo=UTC)),
        Order(id="o-1003", account_id="acct_pdx", total_cents=999, placed_at=datetime(2026, 7, 10, 1, 5, tzinfo=UTC)),
        Order(id="o-2001", account_id="acct_ber", total_cents=760, placed_at=datetime(2026, 7, 9, 7, 30, tzinfo=UTC)),
        Order(id="o-2002", account_id="acct_ber", total_cents=1240, placed_at=datetime(2026, 7, 9, 16, 2, tzinfo=UTC)),
        Order(id="o-3001", account_id="acct_tyo", total_cents=5300, placed_at=datetime(2026, 7, 9, 22, 45, tzinfo=UTC)),
    ]
    for order in orders:
        store.add_order(order)
    return store
