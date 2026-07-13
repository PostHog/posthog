# Catches: daily report boundaries computed on the UTC calendar date instead of the account's timezone, shifting west-of-UTC accounts' reports off by a day.
import sys
from datetime import UTC, datetime
from pathlib import Path

import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from acme_reports.models import Account, Order
from acme_reports.reports import generate_daily_report
from acme_reports.store import InMemoryStore


def _order(store: InMemoryStore, order_id: str, account_id: str, iso_utc: str, cents: int = 1000) -> None:
    placed_at = datetime.fromisoformat(iso_utc).replace(tzinfo=UTC)
    store.add_order(Order(id=order_id, account_id=account_id, total_cents=cents, placed_at=placed_at))


class TestAccountTimezoneBoundaries(unittest.TestCase):
    def test_west_of_utc_account_gets_its_local_day(self) -> None:
        # 2026-03-10 01:30 UTC is 2026-03-09 18:30 in Los Angeles (PDT, UTC-7).
        store = InMemoryStore()
        account = Account(
            id="a1", name="Bridge City Goods", email="ops@bridgecity.example", timezone="America/Los_Angeles"
        )
        store.add_account(account)
        _order(store, "o1", "a1", "2026-03-09T08:00:00", 4200)  # Mar 9 01:00 PDT - in local day
        _order(store, "o2", "a1", "2026-03-09T23:30:00", 1850)  # Mar 9 16:30 PDT - in local day
        _order(store, "o3", "a1", "2026-03-10T01:00:00", 999)  # Mar 9 18:00 PDT - in local day
        _order(store, "o4", "a1", "2026-03-09T05:00:00", 700)  # Mar 8 22:00 PDT - previous local day
        _order(store, "o5", "a1", "2026-03-10T08:00:00", 1200)  # Mar 10 01:00 PDT - next local day

        now = datetime(2026, 3, 10, 1, 30, tzinfo=UTC)
        report = generate_daily_report(store, account, now=now)

        self.assertEqual(report.date, "2026-03-09")
        self.assertEqual(set(report.order_ids), {"o1", "o2", "o3"})
        self.assertEqual(report.order_count, 3)
        self.assertEqual(report.total_cents, 4200 + 1850 + 999)

    def test_east_of_utc_account_gets_its_local_day(self) -> None:
        # 2026-03-09 22:00 UTC is 2026-03-10 07:00 in Tokyo (UTC+9).
        store = InMemoryStore()
        account = Account(id="a2", name="Shibuya Prints", email="store@shibuyaprints.example", timezone="Asia/Tokyo")
        store.add_account(account)
        _order(store, "t1", "a2", "2026-03-09T16:00:00", 5300)  # Mar 10 01:00 JST - in local day
        _order(store, "t2", "a2", "2026-03-09T12:00:00", 800)  # Mar 9 21:00 JST - previous local day
        _order(store, "t3", "a2", "2026-03-09T21:30:00", 2100)  # Mar 10 06:30 JST - in local day

        now = datetime(2026, 3, 9, 22, 0, tzinfo=UTC)
        report = generate_daily_report(store, account, now=now)

        self.assertEqual(report.date, "2026-03-10")
        self.assertEqual(set(report.order_ids), {"t1", "t3"})
        self.assertEqual(report.total_cents, 5300 + 2100)


if __name__ == "__main__":
    unittest.main()
