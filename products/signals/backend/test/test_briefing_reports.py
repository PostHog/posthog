import json
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast

from posthog.test.base import BaseTest

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized
from rest_framework.request import Request

from products.signals.backend.artefact_schemas import ActionabilityChoice, RankingModelResult, RankingScore
from products.signals.backend.briefing_reports import (
    BriefingReportRelation,
    _briefing_order,
    open_report_counts,
    report_details,
    reports_for_briefing,
    summary_lead,
)
from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.report_metric_access import ReportMetricAccessPolicy
from products.signals.backend.test.report_metric_test_fixtures import trends_metric_query


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

    def test_report_details_keep_only_metrics_with_a_saved_snapshot(self) -> None:
        report = self._urgent_report("Checkout fails")
        query = trends_metric_query(
            series=[{"kind": "EventsNode", "event": "$exception", "math": "dau"}], date_from="-14d"
        )

        def metric(metric_id: str, value: float | None) -> dict:
            return {
                "metric_id": metric_id,
                "title": "Affected users",
                "kind": "affected_users",
                "role": "primary",
                "value": value,
                "value_at": "2026-09-30T12:00:00Z" if value is not None else None,
                "series": [3.0, 9.0, 17.0] if value is not None else None,
                "value_format": "count",
                "unit": "users",
                "query": query,
            }

        report.metrics = [metric("measured", 17), metric("not-measured", None), {"metric_id": "broken"}]
        report.summary = "Leaks continue. [Form errors](chart:form-errors)"
        report.charts = [
            {"chart_id": "page-leaves", "title": "Page leaves", "query": query},
            {"chart_id": "broken"},
            {"chart_id": "form-errors", "title": "Form errors", "query": query},
        ]
        report.save(update_fields=["metrics", "charts", "summary"])

        viewer = ReportMetricAccessPolicy(
            request=cast(Request, SimpleNamespace(user=self.user, successful_authenticator=None)), team=self.team
        )
        [details] = report_details(team_id=self.team.id, report_ids=[str(report.id)], metric_access=viewer)
        # Without a viewer the policy reads nothing, so the briefing must hide every metric, as the Inbox does.
        [unreadable] = report_details(
            team_id=self.team.id,
            report_ids=[str(report.id)],
            metric_access=ReportMetricAccessPolicy(request=None, team=self.team),
        )

        assert (details.status, details.priority, details.pull_request_state) == ("ready", "P0", None)
        assert [(m.metric_id, m.value, m.series, m.query) for m in details.metrics] == [
            ("measured", 17, [3.0, 9.0, 17.0], query)
        ]
        assert [(c.chart_id, c.query) for c in details.charts] == [("form-errors", query), ("page-leaves", query)]
        assert unreadable.metrics == []

    def test_open_report_counts_do_not_subtract_a_report_that_was_never_open(self) -> None:
        shown_open = self._urgent_report("Shown, still open")
        self._urgent_report("Not shown")
        resolved = self._urgent_report("Shown, resolved since")
        SignalReport.objects.filter(pk=resolved.pk).update(status=SignalReport.Status.RESOLVED)

        counts = open_report_counts(
            team_id=self.team.id, user=self.user, exclude_report_ids=[str(shown_open.id), str(resolved.id)]
        )

        assert counts.in_project == 1

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


class TestSummaryLead(SimpleTestCase):
    @parameterized.expand(
        [
            ("plain text", "Signups fail.\nPeople leave.", "Signups fail. People leave."),
            ("stops at a section", "Signups fail.\n\n## Impact\nNew teams cannot sign up.", "Signups fail."),
            ("skips an opening heading", "## Summary\nSignups fail.\n## Impact\nMore.", "Signups fail."),
            ("skips a bare opening heading", "##\nSignups fail.", "Signups fail."),
            (
                "keeps underscores in identifiers",
                "The `__init__` method sets `feature__enabled` to false.",
                "The __init__ method sets feature__enabled to false.",
            ),
            ("a hash inside a line stays", "Issue #42 ## fails", "Issue #42 ## fails"),
            (
                "drops chart links and keeps link text",
                "Leaks **typed text**. [Page leaves](chart:page-leaves) See [the form](https://example.com/form).",
                "Leaks typed text. See the form.",
            ),
            ("no summary", None, ""),
        ]
    )
    def test_summary_lead(self, _name: str, summary: str | None, expected: str) -> None:
        assert summary_lead(summary, 300) == expected

    @parameterized.expand([("unclosed labels", "[" * 20_000), ("unclosed destinations", "[a](" * 5_000)])
    def test_summary_lead_stays_fast_on_unclosed_links(self, _name: str, summary: str) -> None:
        started = time.perf_counter()
        summary_lead(summary, 450)
        assert time.perf_counter() - started < 0.5
