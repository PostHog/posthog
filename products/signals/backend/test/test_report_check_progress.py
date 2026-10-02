from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, Literal

import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.signals.backend.models import SignalReport, SignalReportArtefact, SignalReportCheck
from products.signals.backend.report_check_progress import (
    CheckProgressStatus,
    bounded_progress_query,
    evaluate_progress,
    interim_comparison,
    observation_count_query,
    progress_target_type,
)
from products.signals.backend.report_checks import CheckComparison, CheckOperator, MetricThresholdConfig
from products.signals.backend.test.report_metric_test_fixtures import trends_metric_query


class TestProgressEvaluation(SimpleTestCase):
    @parameterized.expand(
        [
            ("counts_on_track", "lte", 70, 4, 4, 1, "proportional", CheckProgressStatus.ON_TRACK),
            ("counts_off_track", "lte", 70, 11, 11, 1, "proportional", CheckProgressStatus.OFF_TRACK),
            ("no_activity", "lte", 70, 0, 0, 1, "proportional", CheckProgressStatus.INSUFFICIENT_DATA),
            ("zero_with_traffic", "lte", 0, 0, 100, 1, "proportional", CheckProgressStatus.ON_TRACK),
            ("early_rate", "lte", 5, 4, 30, 1, "fixed", CheckProgressStatus.ON_TRACK),
            ("early_rate_bad", "lte", 5, 6, 30, 1, "fixed", CheckProgressStatus.OFF_TRACK),
            ("positive_goal", "gte", 70, 11, 11, 1, "proportional", CheckProgressStatus.ON_TRACK),
            ("explicit_sample_minimum", "lte", 70, 4, 4, 10, "proportional", CheckProgressStatus.INSUFFICIENT_DATA),
        ]
    )
    def test_interim_direction(
        self,
        _: str,
        operator: CheckOperator,
        goal: float,
        value: float,
        sample_size: float,
        minimum: int,
        mode: Literal["proportional", "fixed"],
        expected: CheckProgressStatus,
    ) -> None:
        comparison = interim_comparison(
            CheckComparison(operator=operator, value=goal), target_type=mode, fraction=2 / 14
        )
        self.assertEqual(
            evaluate_progress(value=value, comparison=comparison, sample_size=sample_size, minimum=minimum), expected
        )

    @parameterized.expand(
        [
            ("total", "total", None, "proportional"),
            ("distinct_users", "dau", None, "proportional"),
            ("average", "avg", None, "fixed"),
            ("custom_sum", "hogql", "sum(properties.amount)", "proportional"),
            ("custom_average", "hogql", "avg(properties.amount)", "fixed"),
            ("unknown_custom", "hogql", "max(properties.amount) - min(properties.amount)", None),
        ]
    )
    def test_target_inference(
        self, _: str, aggregation: str, expression: str | None, expected: Literal["proportional", "fixed"] | None
    ) -> None:
        series = {"kind": "EventsNode", "event": "example_event", "math": aggregation}
        if expression:
            series["math_hogql"] = expression
        config = MetricThresholdConfig(
            query=trends_metric_query(series=[series]), comparison={"operator": "lte", "value": 5}
        )
        self.assertEqual(progress_target_type(config), expected)

    @parameterized.expand([("A + B", "proportional"), ("100 * A / B", "fixed"), ("A * B", None)])
    def test_formula_targets(self, formula: str, expected: Literal["proportional", "fixed"] | None) -> None:
        query = trends_metric_query(
            series=[{"kind": "EventsNode", "event": "failure"}, {"kind": "EventsNode", "event": "attempt"}]
        )
        query["source"]["trendsFilter"] = {"formula": formula}
        self.assertEqual(
            progress_target_type(MetricThresholdConfig(query=query, comparison={"operator": "lte", "value": 5})),
            expected,
        )

    def test_absolute_bounds_do_not_mutate_the_final_check(self) -> None:
        query = trends_metric_query(series=[{"kind": "EventsNode", "event": "example_event"}])
        original = deepcopy(query)
        start = datetime(2026, 10, 1, 12, 23, tzinfo=UTC)
        end = start + timedelta(hours=3)
        derived = bounded_progress_query(query, start=start, end=end)
        self.assertEqual(
            derived["source"]["dateRange"],
            {"date_from": start.isoformat(), "date_to": end.isoformat(), "explicitDate": True},
        )
        self.assertEqual(derived["source"]["interval"], "hour")
        self.assertEqual(query, original)
        comparison = interim_comparison(
            CheckComparison(operator="between", bounds={"lower": 14, "upper": 28}),
            target_type="proportional",
            fraction=0.5,
        )
        assert comparison.bounds is not None
        self.assertEqual(comparison.bounds.model_dump(), {"lower": 7, "upper": 14})

    def test_rate_evidence_counts_the_denominator_without_mutating_the_metric(self) -> None:
        query = trends_metric_query(
            series=[
                {"kind": "EventsNode", "event": "failure", "math": "dau"},
                {"kind": "EventsNode", "event": "attempt", "math": "dau"},
            ]
        )
        query["source"]["trendsFilter"] = {"formula": "100 * A / B"}
        original = deepcopy(query)
        evidence = observation_count_query(query)
        self.assertEqual(evidence["source"]["series"], [{"kind": "EventsNode", "event": "attempt", "math": "total"}])
        self.assertEqual(evidence["source"]["trendsFilter"], {"formula": "A"})
        self.assertEqual(query, original)


class TestReportCheckProgressAPI(APIBaseTest):
    @time_machine.travel("2026-10-03T12:23:00Z", tick=False)
    def test_read_time_progress_is_cached_and_freezes_at_resolution(self) -> None:
        start = datetime(2026, 10, 1, 12, 23, tzinfo=UTC)
        now = start + timedelta(days=2)
        report = SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.MONITORING, monitoring_started_at=start, title="Example failure"
        )
        query = trends_metric_query(series=[{"kind": "EventsNode", "event": "example_failure"}], date_from="-14d")
        check = SignalReportCheck.objects.for_team(self.team.id).create(
            team=self.team,
            report=report,
            title="Failures stay below 70",
            kind="metric_threshold",
            status="active",
            config={"query": query, "comparison": {"operator": "lte", "value": 70}},
            next_run_at=now + timedelta(days=12),
            expires_at=now + timedelta(days=40),
        )
        url = f"/api/projects/{self.team.id}/signals/reports/{report.id}/checks/progress/"
        initial_check = deepcopy(check.__dict__)
        artefact_count = SignalReportArtefact.objects.filter(report=report).count()
        executed = []

        def run_query(*, query: dict[str, Any], **kwargs: object) -> SimpleNamespace:
            executed.append(query)
            return SimpleNamespace(
                results=[
                    {
                        "aggregated_value": 4,
                        "days": [start.isoformat(), (start + timedelta(hours=1)).isoformat()],
                        "data": [2, 2],
                    }
                ],
                last_refresh=now,
            )

        with patch("products.signals.backend.report_metric_refresh.run_cached_trends_query", side_effect=run_query):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, response.content)
            progress = response.json()[0]
            self.assertEqual(progress["status"], "on_track")
            self.assertEqual(progress["target"], 10)
            self.assertEqual(progress["value"], 4)
            self.assertAlmostEqual(progress["points"][0]["target"], 70 / (14 * 24))
            self.assertEqual(len(executed), 3)
            self.assertEqual(self.client.get(url).json(), response.json())
            self.assertEqual(len(executed), 3)
            ended = now - timedelta(hours=2)
            with time_machine.travel(ended, tick=False):
                report.transition_to(SignalReport.Status.RESOLVED)
                report.save()
            frozen = self.client.get(url).json()[0]
            self.assertEqual(datetime.fromisoformat(frozen["ended_at"].replace("Z", "+00:00")), ended)
            self.assertEqual(len(executed), 6)
            for executed_query in executed:
                self.assertEqual(executed_query["dateRange"]["date_from"], start.isoformat())
                self.assertTrue(executed_query["dateRange"]["explicitDate"])
            self.assertEqual(executed[-1]["dateRange"]["date_to"], ended.isoformat())
        check.refresh_from_db()
        self.assertEqual(check.config, initial_check["config"])
        self.assertEqual(check.next_run_at, initial_check["next_run_at"])
        self.assertEqual(check.runs_remaining, initial_check["runs_remaining"])
        self.assertEqual(check.last_outcome, initial_check["last_outcome"])
        self.assertEqual(SignalReportArtefact.objects.filter(report=report).count(), artefact_count)
        report.save(update_fields=report.transition_to(SignalReport.Status.READY))
        report.refresh_from_db()
        self.assertIsNone(report.monitoring_started_at)
        self.assertIsNone(report.monitoring_ended_at)
        self.assertEqual(self.client.get(url).json(), [])

    @time_machine.travel("2026-10-03T12:23:00Z", tick=False)
    def test_query_permission_blocks_measurement_and_query_disclosure(self) -> None:
        report = SignalReport.objects.create(
            team=self.team,
            status="monitoring",
            monitoring_started_at=datetime(2026, 10, 1, tzinfo=UTC),
            title="Example failure",
        )
        query = trends_metric_query(series=[{"kind": "EventsNode", "event": "example_failure"}])
        SignalReportCheck.objects.for_team(self.team.id).create(
            team=self.team,
            report=report,
            title="Count",
            kind="metric_threshold",
            status="active",
            config={"query": query, "comparison": {"operator": "lte", "value": 70}},
            next_run_at=datetime(2026, 10, 20, tzinfo=UTC),
            expires_at=datetime(2026, 11, 20, tzinfo=UTC),
        )
        token = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            user=self.user, label="Task read only", secure_value=hash_key_value(token), scopes=["task:read"]
        )
        self.client.force_login(self.user)
        self.client.logout()
        with patch("products.signals.backend.report_metric_refresh.run_cached_trends_query") as runner:
            response = self.client.get(
                f"/api/projects/{self.team.id}/signals/reports/{report.id}/checks/progress/",
                HTTP_AUTHORIZATION=f"Bearer {token}",
            )
            self.assertEqual(response.status_code, 403)
            runner.assert_not_called()
