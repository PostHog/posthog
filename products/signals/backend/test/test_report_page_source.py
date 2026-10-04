from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models import Team

from products.signals.backend.models import SignalReport
from products.signals.backend.report_page_source import report_page_source


class TestReportPageSource(BaseTest):
    def _report(self, team: Team | None = None, **fields: Any) -> SignalReport:
        return SignalReport.objects.create(
            **{
                "team": team or self.team,
                "title": "Checkout fails",
                "summary": "Checkout fails for some shoppers.",
                "status": SignalReport.Status.READY,
                "signal_count": 1,
                "total_weight": 1.0,
                "suggested_prompts": ["Fix the token refresh"],
                **fields,
            }
        )

    def _source(self, report_id: str, pull_requests: dict[str, list[str]] | None = None):
        with (
            patch("products.signals.backend.report_page_source.fetch_signals_for_report_sync", return_value=[]),
            patch(
                "products.signals.backend.report_page_source.fetch_implementation_prs_for_reports",
                return_value=pull_requests or {},
            ),
        ):
            return report_page_source(team=self.team, report_id=report_id)

    @parameterized.expand(
        [
            ("a ready report", {}, False, ["Fix the token refresh"]),
            ("a resolved report", {"status": SignalReport.Status.RESOLVED}, False, []),
            ("a report judged not actionable", {"latest_actionability": "not_actionable"}, False, []),
            ("a report already addressed", {"latest_already_addressed": True}, False, []),
            ("a report with a pull request", {}, True, []),
        ]
    )
    def test_offers_prompts_that_start_work_only_for(
        self, _name: str, fields: dict[str, Any], has_pull_request: bool, expected: list[str]
    ) -> None:
        report = self._report(**fields)
        source = self._source(str(report.id), {str(report.id): ["pull request"]} if has_pull_request else None)
        assert source is not None
        assert source.action_prompts == expected

    def test_finds_no_page_for_a_deleted_or_foreign_report(self) -> None:
        deleted = self._report(status=SignalReport.Status.DELETED)
        foreign = self._report(team=Team.objects.create(organization=self.organization))
        assert self._source(str(deleted.id)) is None
        assert self._source(str(foreign.id)) is None
