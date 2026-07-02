from datetime import timedelta

from freezegun import freeze_time
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from products.pulse.backend.sources.scout_reports import (
    MAX_REPORTS,
    SUMMARY_MAX_CHARS,
    TITLE_MAX_CHARS,
    ScoutReportsSource,
)
from products.signals.backend.facade.api import SignalReportSummary


def _summary(**overrides: object) -> SignalReportSummary:
    defaults: dict = {
        "id": "report-1",
        "title": "Checkout errors spiking",
        "summary": "Users hit a 500 on checkout.",
        "total_weight": 2.5,
        "signal_count": 4,
    }
    defaults.update(overrides)
    return SignalReportSummary(**defaults)


class TestScoutReportsGather(BaseTest):
    @freeze_time("2026-07-02T12:00:00Z")
    def test_gather_maps_reports_to_signal_items(self) -> None:
        with patch(
            "products.pulse.backend.sources.scout_reports.get_recent_reports", return_value=[_summary()]
        ) as facade_mock:
            items = ScoutReportsSource().gather(self.team, None, period_days=7)

        team_id, kwargs = facade_mock.call_args.args[0], facade_mock.call_args.kwargs
        assert team_id == self.team.id
        assert kwargs["limit"] == MAX_REPORTS
        assert kwargs["since"] == timezone.now() - timedelta(days=7)
        assert len(items) == 1
        item = items[0]
        assert item.source == "scout_reports"
        assert item.kind == "signal"
        assert item.title == "Checkout errors spiking"
        assert item.description == "Users hit a 500 on checkout."
        assert item.numbers == {"weight": 2.5, "signal_count": 4}
        assert item.evidence == [{"type": "signal_report", "ref": "report-1", "label": "Checkout errors spiking"}]
        assert item.fingerprint_hint == "scout_reports:report-1"

    def test_long_report_text_truncated(self) -> None:
        long_report = _summary(title="t" * 500, summary="s" * 5000)
        with patch("products.pulse.backend.sources.scout_reports.get_recent_reports", return_value=[long_report]):
            items = ScoutReportsSource().gather(self.team, None, period_days=7)

        assert len(items[0].title) == TITLE_MAX_CHARS
        assert len(items[0].description) == SUMMARY_MAX_CHARS
