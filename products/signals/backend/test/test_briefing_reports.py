import json
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import connection
from django.test import SimpleTestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from parameterized import parameterized
from rest_framework.request import Request

from products.signals.backend.artefact_schemas import ActionabilityChoice, RankingModelResult, RankingScore
from products.signals.backend.briefing_reports import (
    BriefingReportRelation,
    _briefing_pick,
    _BriefingCandidate,
    _ServedScores,
    open_report_counts,
    report_details,
    reports_for_briefing,
    summary_lead,
)
from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.report_metric_access import ReportMetricAccessPolicy
from products.signals.backend.test.report_metric_test_fixtures import trends_metric_query

SOURCE_PRODUCTS = "products.signals.backend.briefing_reports.fetch_source_products_for_reports"


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

    def _named_report(self, title: str) -> SignalReport:
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
            type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
            content=json.dumps([{"github_login": "reviewer", "user_uuid": str(self.user.uuid)}]),
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

        # By default an unowned P0 is for the person the same way the briefing ranks it, so both counts agree.
        assert (counts.in_project, counts.for_person) == (1, 1)

    @parameterized.expand([("included", True, {"Mine", "Nobody's P0"}), ("excluded", False, {"Mine"})])
    def test_include_unowned_decides_whether_a_p0_nobody_owns_is_a_candidate(
        self, _name: str, include_unowned: bool, expected: set[str]
    ) -> None:
        self._named_report("Mine")
        self._urgent_report("Nobody's P0")

        reports = reports_for_briefing(team_id=self.team.id, user_id=self.user.id, include_unowned=include_unowned)

        assert {report.title for report in reports} == expected

    def test_excluding_unowned_reports_leaves_them_in_the_project_count_only(self) -> None:
        self._named_report("Mine")
        self._urgent_report("Nobody's P0")

        counts = open_report_counts(team_id=self.team.id, user=self.user, include_unowned=False)

        assert (counts.in_project, counts.for_person) == (2, 1)

    def test_merge_chance_comes_from_the_latest_readable_served_score(self) -> None:
        rescored = self._urgent_report("Rescored")
        self._score(rescored, 0.1, readable=True, age=timedelta(days=2))
        self._score(rescored, 0.7, readable=True, age=timedelta(hours=1))
        unreadable = self._urgent_report("Unreadable head")
        self._score(unreadable, 0.9, readable=False, age=timedelta(hours=1))
        unscored = self._urgent_report("Unscored")
        truncated = self._urgent_report("Truncated score")
        self._score(truncated, 0.8, readable=True, age=timedelta(days=1))
        SignalReportArtefact.objects.create(
            team=self.team,
            report=truncated,
            type=SignalReportArtefact.ArtefactType.RANKING_SCORE,
            content='{"scored_at": "2026-09-20T12:00:00Z", "results": {',
        )

        reports = reports_for_briefing(team_id=self.team.id, user_id=self.user.id)

        assert {report.relation for report in reports} == {BriefingReportRelation.URGENT_UNOWNED}
        assert {report.title: report.pr_merged_probability for report in reports} == {
            rescored.title: 0.7,
            unreadable.title: None,
            unscored.title: None,
            truncated.title: None,
        }

    def test_query_count_does_not_grow_with_the_candidates(self) -> None:
        def queries() -> int:
            with CaptureQueriesContext(connection) as captured:
                reports_for_briefing(team_id=self.team.id, user_id=self.user.id, limit=5)
            return len(captured.captured_queries)

        self._score(self._urgent_report("First"), 0.5, readable=True, age=timedelta(hours=1))
        with patch(SOURCE_PRODUCTS, return_value={}):
            one_candidate = queries()
            for index in range(6):
                self._score(self._urgent_report(f"More {index}"), 0.5, readable=True, age=timedelta(hours=1))
            seven_candidates = queries()

        assert seven_candidates == one_candidate

    def test_an_older_report_with_a_high_merge_chance_beats_newer_ones(self) -> None:
        reports = []
        for index in range(6):
            report = SignalReport.objects.create(
                team=self.team,
                status=SignalReport.Status.READY,
                title=f"Report {index}",
                summary="Summary",
                signal_count=1,
                total_weight=1.0,
            )
            SignalReportArtefact.objects.create(
                team=self.team,
                report=report,
                type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
                content=json.dumps([{"github_login": "reviewer", "user_uuid": str(self.user.uuid)}]),
            )
            self._score(report, 0.9 if index == 5 else 0.1, readable=True, age=timedelta(hours=1))
            reports.append(report)
        for index, report in enumerate(reports):
            SignalReport.objects.filter(pk=report.pk).update(updated_at=timezone.now() - timedelta(days=index))

        [top] = reports_for_briefing(team_id=self.team.id, user_id=self.user.id, limit=1)

        assert (top.title, top.relation) == ("Report 5", BriefingReportRelation.SUGGESTED_REVIEWER)


_Spec = tuple[str, BriefingReportRelation, str | None, float | None, float | None, float | None]
WAITING = BriefingReportRelation.WAITING_FOR_YOU
REVIEW = BriefingReportRelation.SUGGESTED_REVIEWER


def _candidates(specs: list[_Spec]) -> list[_BriefingCandidate]:
    return [
        _BriefingCandidate(
            report_id=report_id,
            relation=relation,
            priority=priority,
            updated_at=datetime(2026, 9, 29, tzinfo=UTC),
            scores=_ServedScores(pr_merged=pr_merged, action=action, dismiss_wrong_lift=dismiss_wrong_lift),
        )
        for report_id, relation, priority, pr_merged, action, dismiss_wrong_lift in specs
    ]


class TestBriefingPick(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "merge chance decides across relations",
                [
                    ("w1", WAITING, "P1", 0.02, None, None),
                    ("s1", REVIEW, "P3", 0.4, None, None),
                    ("c1", BriefingReportRelation.CLAIMED, "P3", 0.1, None, None),
                ],
                ["s1", "c1", "w1"],
            ),
            (
                "a high action chance ranks a report with a low merge chance",
                [
                    ("merge", REVIEW, "P3", 0.3, 0.1, None),
                    ("middle", REVIEW, "P3", 0.2, 0.2, None),
                    ("act", WAITING, "P2", 0.01, 0.9, None),
                ],
                ["act", "merge", "middle"],
            ),
            (
                "the two heads compare by rank, not by value",
                [
                    ("merge", REVIEW, "P3", 0.05, 0.001, None),
                    ("act", REVIEW, "P2", 0.01, 0.5, None),
                    ("low", REVIEW, "P3", 0.02, 0.2, None),
                ],
                ["act", "merge", "low"],
            ),
            (
                "P0 comes first",
                [
                    ("s1", REVIEW, "P1", 0.9, 0.9, None),
                    ("u1", BriefingReportRelation.URGENT_UNOWNED, "P0", 0.01, None, None),
                ],
                ["u1", "s1"],
            ),
            (
                "unscored reports follow scored ones",
                [("a", REVIEW, "P1", None, None, None), ("b", REVIEW, "P3", None, 0.1, None)],
                ["b", "a"],
            ),
            (
                "a report likely dismissed as wrong is hidden unless it is P0",
                [
                    ("s1", REVIEW, "P2", 0.9, None, 5.0),
                    ("s2", REVIEW, "P2", 0.1, None, 1.0),
                    ("u1", BriefingReportRelation.URGENT_UNOWNED, "P0", 0.1, None, 5.0),
                ],
                ["u1", "s2"],
            ),
        ]
    )
    def test_briefing_pick(self, _name: str, specs: list[_Spec], expected: list[str]) -> None:
        assert [c.report_id for c in _briefing_pick(_candidates(specs), limit=None)] == expected

    def test_the_top_n_is_always_the_first_n_of_the_same_list(self) -> None:
        candidates = _candidates(
            [
                ("w1", WAITING, "P2", 0.05, 0.6, None),
                ("w2", WAITING, "P3", None, None, None),
                ("s1", REVIEW, "P3", 0.3, 0.1, None),
                ("s2", REVIEW, "P1", 0.2, None, None),
                ("c1", BriefingReportRelation.CLAIMED, "P4", 0.25, 0.3, None),
            ]
        )
        full = [c.report_id for c in _briefing_pick(candidates, limit=None)]

        for limit in range(1, len(candidates) + 1):
            assert [c.report_id for c in _briefing_pick(candidates, limit=limit)] == full[:limit]


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
