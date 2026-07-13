# Catches: a timezone fix that breaks UTC accounts, order filtering by account, empty days, or the report shape.
import sys
from datetime import UTC, datetime
from pathlib import Path

import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from acme_reports.emailer import render_report_email
from acme_reports.models import Account, Order
from acme_reports.reports import generate_daily_report
from acme_reports.store import InMemoryStore


def _order(store: InMemoryStore, order_id: str, account_id: str, iso_utc: str, cents: int = 1000) -> None:
    placed_at = datetime.fromisoformat(iso_utc).replace(tzinfo=UTC)
    store.add_order(Order(id=order_id, account_id=account_id, total_cents=cents, placed_at=placed_at))


class TestDailyReportBasics(unittest.TestCase):
    def setUp(self) -> None:
        self.store = InMemoryStore()
        self.account = Account(id="a1", name="Kiez Kaffee", email="hallo@kiezkaffee.example", timezone="UTC")
        self.store.add_account(self.account)
        self.now = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)

    def test_utc_account_report_covers_the_utc_day(self) -> None:
        _order(self.store, "o1", "a1", "2026-03-10T03:00:00", 760)
        _order(self.store, "o2", "a1", "2026-03-10T11:00:00", 1240)
        _order(self.store, "o3", "a1", "2026-03-09T23:00:00", 500)  # previous day
        report = generate_daily_report(self.store, self.account, now=self.now)
        self.assertEqual(report.date, "2026-03-10")
        self.assertEqual(set(report.order_ids), {"o1", "o2"})
        self.assertEqual(report.total_cents, 2000)

    def test_other_accounts_orders_are_excluded(self) -> None:
        _order(self.store, "o1", "a1", "2026-03-10T03:00:00", 760)
        _order(self.store, "x1", "someone-else", "2026-03-10T04:00:00", 9999)
        report = generate_daily_report(self.store, self.account, now=self.now)
        self.assertEqual(set(report.order_ids), {"o1"})

    def test_day_with_no_orders_reports_zero(self) -> None:
        report = generate_daily_report(self.store, self.account, now=self.now)
        self.assertEqual(report.order_count, 0)
        self.assertEqual(report.total_cents, 0)
        self.assertEqual(report.order_ids, ())

    def test_email_renders_report_totals(self) -> None:
        _order(self.store, "o1", "a1", "2026-03-10T03:00:00", 123456)
        report = generate_daily_report(self.store, self.account, now=self.now)
        body = render_report_email(self.account, report)
        self.assertIn("Orders: 1", body)
        self.assertIn("$1,234.56", body)
        self.assertIn(report.date, body)


if __name__ == "__main__":
    unittest.main()
