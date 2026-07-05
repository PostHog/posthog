from datetime import timedelta

from freezegun import freeze_time
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from products.pulse.backend.sources.signal_reports import (
    MAX_REPORTS,
    SUMMARY_MAX_CHARS,
    TITLE_MAX_CHARS,
    SignalReportsSource,
)
from products.signals.backend.facade.api import SignalReportSummary
from products.signals.backend.models import SignalReport


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
            items = SignalReportsSource().gather(self.team, None, period_days=7)

        team_id, kwargs = facade_mock.call_args.args[0], facade_mock.call_args.kwargs
        assert team_id == self.team.id
        assert kwargs["limit"] == MAX_REPORTS
        assert kwargs["since"] == timezone.now() - timedelta(days=7)
        assert len(items) == 1
        item = items[0]
        assert item.source == "signal_reports"
        assert item.kind == "signal"
        assert item.title == "Checkout errors spiking"
        assert item.description == "Users hit a 500 on checkout."
        assert item.numbers == {"weight": 2.5, "signal_count": 4}
        assert item.evidence == [{"type": "signal_report", "ref": "report-1", "label": "Checkout errors spiking"}]
        assert item.fingerprint_hint == "signal_reports:report-1"

    def test_long_report_text_truncated(self) -> None:
        long_report = _summary(title="t" * 500, summary="s" * 5000)
        with patch("products.pulse.backend.sources.signal_reports.get_recent_reports", return_value=[long_report]):
            items = SignalReportsSource().gather(self.team, None, period_days=7)

        assert len(items[0].title) == TITLE_MAX_CHARS
        assert len(items[0].description) == SUMMARY_MAX_CHARS

    def test_replay_vision_report_renders_through_the_real_facade(self) -> None:
        # Integration path for the widened read: a replay-vision-derived report row (its signals
        # carry scanner extras — scanner name, session_id, exported_asset_id — that live in
        # ClickHouse, which the facade never reads) flows through the real get_recent_reports
        # into a plain signal item. Only the CH report-id query is patched.
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        report = SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.READY,
            title="Rage-click friction on /billing (scanner: checkout-watcher)",
            summary="Replay vision flagged a disabled CTA rage-clicked in session 0197-abc (design_flaw, 0.7).",
            total_weight=1.4,
            signal_count=2,
        )
        with patch(
            "products.signals.backend.temporal.signal_queries.fetch_report_ids_for_source_products",
            return_value={str(report.id)},
        ):
            items = SignalReportsSource().gather(self.team, None, period_days=7)

        assert len(items) == 1
        item = items[0]
        # The source reads title/summary/weight/count only — scanner extras never surface here.
        assert item.kind == "signal"
        assert item.title == "Rage-click friction on /billing (scanner: checkout-watcher)"
        assert item.numbers == {"weight": 1.4, "signal_count": 2}
        assert item.evidence == [
            {
                "type": "signal_report",
                "ref": str(report.id),
                "label": "Rage-click friction on /billing (scanner: checkout-watcher)",
            }
        ]
        assert item.fingerprint_hint == f"signal_reports:{report.id}"
