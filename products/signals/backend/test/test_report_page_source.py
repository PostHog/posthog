from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models import Team, User

from products.access_control.backend.models.access_control import AccessControl
from products.signals.backend.models import SignalActorKind, SignalReport, SignalReportArtefact
from products.signals.backend.report_access import may_read_reports
from products.signals.backend.report_page_source import report_agent_texts, report_page_source


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

    def test_finds_no_page_or_summary_for_a_deleted_or_foreign_report(self) -> None:
        deleted = self._report(status=SignalReport.Status.DELETED)
        foreign = self._report(team=Team.objects.create(organization=self.organization))
        for report in (deleted, foreign):
            assert self._source(str(report.id)) is None


class TestReportAccess(BaseTest):
    def test_checks_the_environment_it_is_given(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        environment = Team.objects.create(organization=self.organization, parent_team=self.team)
        AccessControl.objects.create(team=environment, resource="task", resource_id=None, access_level="none")
        member = User.objects.create_and_join(self.organization, "member@example.com", "testtest")

        assert (may_read_reports(user=member, team=self.team), may_read_reports(user=member, team=environment)) == (
            True,
            False,
        )


class TestReportAgentTexts(BaseTest):
    def test_returns_the_newest_texts_an_agent_wrote(self) -> None:
        report = SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.READY, title="t", summary="s", signal_count=1, total_weight=1.0
        )
        for content, actor_kind, created_by in [
            ("Old agent note.", SignalActorKind.AGENT, self.user),
            ("New agent note.", SignalActorKind.AGENT, self.user),
            ("By a person.", SignalActorKind.USER, self.user),
            ("By a deleted person.", SignalActorKind.USER, None),
            ("Legacy person note.", None, self.user),
        ]:
            SignalReportArtefact.objects.create(
                team=self.team,
                report=report,
                type=SignalReportArtefact.ArtefactType.NOTE,
                content=content,
                actor_kind=actor_kind,
                created_by=created_by,
            )

        texts = report_agent_texts(team=self.team, report_id=str(report.id), types=["note"], per_type=1)

        assert [text.content for text in texts] == ["New agent note."]
