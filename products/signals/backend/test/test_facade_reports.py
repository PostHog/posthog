from datetime import timedelta
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from posthog.models.organization import Organization
from posthog.models.team import Team

from products.signals.backend.facade.api import SignalReportSummary, get_recent_reports
from products.signals.backend.models import SignalReport

_FETCH_SCOUT_IDS = "products.signals.backend.temporal.signal_queries.fetch_report_ids_for_source_products"


class TestGetRecentReports(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()

    def _report(self, **kwargs: Any) -> SignalReport:
        defaults: dict[str, Any] = {
            "team": self.team,
            "status": SignalReport.Status.READY,
            "title": "Checkout errors spiking",
            "summary": "Users hit a 500 on checkout.",
            "total_weight": 1.5,
            "signal_count": 3,
        }
        defaults.update(kwargs)
        return SignalReport.objects.create(**defaults)

    def _recent(self, scout_ids: set[str] | None = None, **kwargs: Any) -> list[SignalReportSummary]:
        if scout_ids is None:
            scout_ids = {str(report_id) for report_id in SignalReport.objects.values_list("id", flat=True)}
        kwargs.setdefault("since", timezone.now() - timedelta(days=7))
        with patch(_FETCH_SCOUT_IDS, return_value=scout_ids):
            return get_recent_reports(self.team.id, **kwargs)

    def test_returns_report_summaries_newest_first(self) -> None:
        older = self._report(title="Older report")
        SignalReport.objects.filter(id=older.id).update(created_at=timezone.now() - timedelta(days=2))
        newer = self._report()

        results = self._recent()

        assert [result.id for result in results] == [str(newer.id), str(older.id)]
        assert results[0] == SignalReportSummary(
            id=str(newer.id),
            title="Checkout errors spiking",
            summary="Users hit a 500 on checkout.",
            total_weight=1.5,
            signal_count=3,
        )

    def test_scoped_to_scout_and_replay_vision_never_pulse(self) -> None:
        source_report = self._report(title="Scout or replay-vision finding")
        self._report(title="Report formed from pulse's own signals")

        with patch(_FETCH_SCOUT_IDS, return_value={str(source_report.id)}) as fetch_mock:
            results = get_recent_reports(self.team.id, since=timezone.now() - timedelta(days=7))

        assert [result.id for result in results] == [str(source_report.id)]
        # Scout and replay-vision reports are eligible input; pulse's own output never is.
        assert set(fetch_mock.call_args.args[1]) == {"signals_scout", "replay_vision"}

    def test_no_scout_reports_returns_empty(self) -> None:
        self._report()

        assert self._recent(scout_ids=set()) == []

    @parameterized.expand(
        [
            ("ready", SignalReport.Status.READY, 1),
            ("pending_input", SignalReport.Status.PENDING_INPUT, 1),
            ("resolved", SignalReport.Status.RESOLVED, 1),
            ("failed", SignalReport.Status.FAILED, 1),
            ("deleted", SignalReport.Status.DELETED, 0),
            ("suppressed", SignalReport.Status.SUPPRESSED, 0),
        ]
    )
    def test_status_filtering(self, _name: str, report_status: SignalReport.Status, expected_count: int) -> None:
        self._report(status=report_status)

        assert len(self._recent()) == expected_count

    @parameterized.expand(
        [
            ("null_title", {"title": None}),
            ("empty_title", {"title": ""}),
            ("null_summary", {"summary": None}),
            ("empty_summary", {"summary": ""}),
        ]
    )
    def test_reports_without_authored_content_excluded(self, _name: str, overrides: dict[str, Any]) -> None:
        self._report(**overrides)

        assert self._recent() == []

    def test_returns_empty_without_ai_consent(self) -> None:
        self._report()
        self.organization.is_ai_data_processing_approved = False
        self.organization.save()

        assert self._recent() == []

    def test_since_and_limit(self) -> None:
        old = self._report(title="Too old")
        SignalReport.objects.filter(id=old.id).update(created_at=timezone.now() - timedelta(days=10))
        for i in range(3):
            self._report(title=f"Report {i}")

        results = self._recent(limit=2)

        assert len(results) == 2
        assert all(result.title != "Too old" for result in results)

    def test_other_team_reports_excluded(self) -> None:
        other_org = Organization.objects.create(name="Other", is_ai_data_processing_approved=True)
        other_team = Team.objects.create(organization=other_org, name="Other team")
        self._report(team=other_team)

        assert self._recent() == []
