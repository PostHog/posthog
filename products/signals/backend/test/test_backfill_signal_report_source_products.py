from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.management import call_command

from products.signals.backend.models import SignalReport

BACKFILL_PATH = (
    "products.signals.backend.management.commands."
    "backfill_signal_report_source_products.fetch_source_products_for_reports"
)


class TestBackfillSignalReportSourceProducts(APIBaseTest):
    def _report(self, source_products=None) -> SignalReport:
        return SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.READY, source_products=source_products or []
        )

    def test_backfill_populates_from_clickhouse(self):
        report = self._report()
        with patch(BACKFILL_PATH, return_value={str(report.id): ["error_tracking", "signals_scout"]}):
            call_command("backfill_signal_report_source_products", "--team-id", str(self.team.id))
        report.refresh_from_db()
        assert report.source_products == ["error_tracking", "signals_scout"]

    def test_dry_run_does_not_write(self):
        report = self._report()
        with patch(BACKFILL_PATH, return_value={str(report.id): ["signals_scout"]}):
            call_command("backfill_signal_report_source_products", "--team-id", str(self.team.id), "--dry-run")
        report.refresh_from_db()
        assert report.source_products == []

    def test_idempotent_when_already_current(self):
        report = self._report(source_products=["signals_scout"])
        with patch(BACKFILL_PATH, return_value={str(report.id): ["signals_scout"]}) as fetch_mock:
            call_command("backfill_signal_report_source_products", "--team-id", str(self.team.id))
            assert fetch_mock.called
        report.refresh_from_db()
        assert report.source_products == ["signals_scout"]
