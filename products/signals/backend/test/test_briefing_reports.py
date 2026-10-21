import json
import time
from datetime import timedelta
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

from posthog.models import Team

from products.signals.backend.artefact_schemas import ActionabilityChoice
from products.signals.backend.briefing_reports import report_details, summary_lead
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

    @parameterized.expand(
        [
            ("ready", SignalReport.Status.READY, False, "ready"),
            ("monitoring_enabled", SignalReport.Status.MONITORING, True, "monitoring"),
            ("monitoring_disabled", SignalReport.Status.MONITORING, False, "resolved"),
            (
                "monitoring_unavailable",
                SignalReport.Status.MONITORING,
                RuntimeError("flag service unavailable"),
                "resolved",
            ),
        ]
    )
    def test_report_details_keep_only_metrics_with_a_saved_snapshot(
        self, _name: str, status: str, flag_result: bool | Exception, expected_status: str
    ) -> None:
        report = self._urgent_report("Checkout fails")
        report.status = status
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
        report.save(update_fields=["status", "metrics", "charts", "summary"])
        other_reports = [self._urgent_report(f"Other report {index}") for index in range(2)]
        SignalReport.objects.filter(id__in=[other.id for other in other_reports]).update(status=status)
        report_ids = [str(item.id) for item in [report, *other_reports]]

        viewer = ReportMetricAccessPolicy(
            request=cast(Request, SimpleNamespace(user=self.user, successful_authenticator=None)), team=self.team
        )
        # A newer judgment stored under another team must not leak into this team's details.
        cross_team = SignalReportArtefact.objects.create(
            team=Team.objects.create(organization=self.organization),
            report=report,
            type=SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT,
            content=json.dumps({"priority": "P4"}),
        )
        SignalReportArtefact.objects.filter(pk=cross_team.pk).update(created_at=timezone.now() + timedelta(hours=1))

        with (
            patch(
                "products.signals.backend.report_content_gates.feature_enabled_or_false",
                return_value=flag_result if isinstance(flag_result, bool) else False,
                side_effect=flag_result if isinstance(flag_result, Exception) else None,
            ) as evaluate,
            CaptureQueriesContext(connection) as queries,
        ):
            results = report_details(team_id=self.team.id, report_ids=report_ids, metric_access=viewer)
        assert len(results) == len(report_ids)
        assert {item.status for item in results} == {expected_status}
        team_gate_reads = [
            query
            for query in queries
            if query["sql"].startswith("SELECT")
            and 'FROM "posthog_team"' in query["sql"]
            and '"organization_id"' in query["sql"]
        ]
        expected_gate_reads = int(status == SignalReport.Status.MONITORING)
        assert evaluate.call_count == expected_gate_reads
        assert len(team_gate_reads) == expected_gate_reads
        details = next(item for item in results if item.report_id == str(report.id))
        # Without a viewer the policy reads nothing, so the briefing must hide every metric, as the Inbox does.
        [unreadable] = report_details(
            team_id=self.team.id,
            report_ids=[str(report.id)],
            metric_access=ReportMetricAccessPolicy(request=None, team=self.team),
        )

        assert (details.status, details.priority, details.pull_request_state) == (expected_status, "P0", None)
        assert [(m.metric_id, m.value, m.series, m.query) for m in details.metrics] == [
            ("measured", 17, [3.0, 9.0, 17.0], query)
        ]
        assert [(c.chart_id, c.query) for c in details.charts] == [("form-errors", query), ("page-leaves", query)]
        assert unreadable.metrics == []


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
