import json
from datetime import UTC, datetime, timedelta

from posthog.test.base import BaseTest

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized

from products.signals.backend.artefact_schemas import ActionabilityChoice, RankingModelResult, RankingScore
from products.signals.backend.briefing_reports import BriefingReportRelation, _briefing_order, reports_for_briefing
from products.signals.backend.models import SignalReport, SignalReportArtefact


class TestReportsForBriefing(BaseTest):
    def _urgent_report(self, title: str) -> SignalReport:
        report = SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.READY,
            title=title,
            summary="Summary",
            signal_count=1,
            total_weight=1.0,
            latest_actionability=ActionabilityChoice.IMMEDIATELY_ACTIONABLE.value,
        )
        SignalReportArtefact.objects.create(
            team=self.team,
            report=report,
            type=SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT,
            content=json.dumps({"priority": "P0"}),
        )
        return report

    def _score(self, report: SignalReport, pr_merged: float, *, readable: bool, age: timedelta) -> None:
        served = RankingModelResult(
            model_name="report_embeddings",
            model_version="2026-09-01",
            model_kind="xgboost",
            roles=["served"],
            feature_schema_version=1,
            status="scored",
            scores={"open": 0.5, "pr_merged": pr_merged},
            metadata={"heads": [{"head": "open", "readable": True}, {"head": "pr_merged", "readable": readable}]},
        )
        artefact = SignalReportArtefact.objects.create(
            team=self.team,
            report=report,
            type=SignalReportArtefact.ArtefactType.RANKING_SCORE,
            content=RankingScore(
                scored_at=datetime(2026, 9, 20, 12, 0, tzinfo=UTC),
                manifest_version="manifest",
                served_key=served.key,
                results={served.key: served},
            ).model_dump_json(),
        )
        SignalReportArtefact.objects.filter(pk=artefact.pk).update(created_at=timezone.now() - age)

    def test_merge_chance_comes_from_the_latest_readable_served_score(self) -> None:
        rescored = self._urgent_report("Rescored")
        self._score(rescored, 0.1, readable=True, age=timedelta(days=2))
        self._score(rescored, 0.7, readable=True, age=timedelta(hours=1))
        unreadable = self._urgent_report("Unreadable head")
        self._score(unreadable, 0.9, readable=False, age=timedelta(hours=1))
        unscored = self._urgent_report("Unscored")

        reports = reports_for_briefing(team_id=self.team.id, user_id=self.user.id)

        assert {report.relation for report in reports} == {BriefingReportRelation.URGENT_UNOWNED}
        assert {report.title: report.pr_merged_probability for report in reports} == {
            rescored.title: 0.7,
            unreadable.title: None,
            unscored.title: None,
        }


class TestBriefingOrder(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "a report waiting for the person beats one they claimed",
                [
                    ("a", "P3", 0.9, BriefingReportRelation.CLAIMED),
                    ("b", "P1", 0.1, BriefingReportRelation.WAITING_FOR_YOU),
                ],
                ["b", "a"],
            ),
            (
                "merge chance beats priority inside a relation",
                [
                    ("a", "P2", 0.8, BriefingReportRelation.SUGGESTED_REVIEWER),
                    ("b", "P1", 0.2, BriefingReportRelation.SUGGESTED_REVIEWER),
                ],
                ["a", "b"],
            ),
            (
                "P0 stays first",
                [
                    ("b", "P1", 0.9, BriefingReportRelation.SUGGESTED_REVIEWER),
                    ("a", "P0", 0.05, BriefingReportRelation.SUGGESTED_REVIEWER),
                ],
                ["a", "b"],
            ),
            (
                "unscored reports follow scored ones",
                [
                    ("a", "P1", None, BriefingReportRelation.SUGGESTED_REVIEWER),
                    ("b", "P3", 0.1, BriefingReportRelation.SUGGESTED_REVIEWER),
                ],
                ["b", "a"],
            ),
        ]
    )
    def test_briefing_order(
        self, _name: str, reports: list[tuple[str, str, float | None, BriefingReportRelation]], expected: list[str]
    ) -> None:
        updated_at = datetime(2026, 9, 29, tzinfo=UTC)
        ordered = sorted(reports, key=lambda r: _briefing_order(r[3], r[1], r[2], updated_at))

        assert [report_id for report_id, *_ in ordered] == expected
