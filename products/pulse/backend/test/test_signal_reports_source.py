from datetime import timedelta

from freezegun import freeze_time
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from posthog.rbac.user_access_control import UserAccessControl

from products.pulse.backend.config import (
    SIGNAL_REPORT_SUMMARY_MAX_CHARS,
    SIGNAL_REPORT_TITLE_MAX_CHARS,
    SIGNAL_REPORTS_MAX,
)
from products.pulse.backend.sources.signal_reports import SignalReportsSource
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


class TestSignalReportsGather(BaseTest):
    @freeze_time("2026-07-02T12:00:00Z")
    def test_gather_maps_reports_to_signal_items(self) -> None:
        with patch(
            "products.pulse.backend.sources.signal_reports.get_recent_reports", return_value=[_summary()]
        ) as facade_mock:
            items = SignalReportsSource().gather(
                self.team, None, lookback_days=7, user_access_control=UserAccessControl(user=self.user, team=self.team)
            )

        team_id, kwargs = facade_mock.call_args.args[0], facade_mock.call_args.kwargs
        assert team_id == self.team.id
        assert kwargs["limit"] == SIGNAL_REPORTS_MAX
        assert kwargs["since"] == timezone.now() - timedelta(days=7)
        assert len(items) == 1
        item = items[0]
        assert item.source == "signal_reports"
        assert item.kind == "signal"
        assert item.title == "Checkout errors spiking"
        assert item.description == "Users hit a 500 on checkout."
        assert item.metrics == {"weight": 2.5, "signal_count": 4}
        evidence = item.evidence[0]
        assert (evidence.type, evidence.ref, evidence.label) == ("signal_report", "report-1", "Checkout errors spiking")
        assert evidence.url == f"/project/{self.team.id}/inbox/reports/report-1"
        assert item.fingerprint_hint == "signal_report:report-1"

    def test_long_report_text_truncated_with_marker(self) -> None:
        long_report = _summary(title="t" * 500, summary="s" * 5000)
        with patch("products.pulse.backend.sources.signal_reports.get_recent_reports", return_value=[long_report]):
            items = SignalReportsSource().gather(
                self.team, None, lookback_days=7, user_access_control=UserAccessControl(user=self.user, team=self.team)
            )

        assert len(items[0].title) == SIGNAL_REPORT_TITLE_MAX_CHARS
        assert len(items[0].description) == SIGNAL_REPORT_SUMMARY_MAX_CHARS
        assert items[0].title.endswith("…")
        assert items[0].description.endswith("…")
