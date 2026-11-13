import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

import requests
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from parameterized import parameterized
from rest_framework import status
from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.models.scoping import team_scope
from posthog.temporal.schedule import schedules

from products.metrics.backend.facade.contracts import MAX_RECORDING_RULES_PER_TEAM, RecordingRuleError
from products.metrics.backend.facade.temporal import create_metrics_recording_rules_schedule
from products.metrics.backend.models import MetricRecordingRule
from products.metrics.backend.recording_rules.evaluation import (
    MAX_SERIES,
    evaluate_team_recording_rules,
    teams_with_recording_rules,
)
from products.metrics.backend.recording_rules.logic import update_rule, validate_rule
from products.metrics.backend.recording_rules.otlp import RecordedSample, export_request
from products.metrics.backend.temporal.recording_rules import (
    MetricsRecordingRulesWorkflow,
    RecordingRulesInputs,
    TeamRecordingRulesInputs,
)

_INGEST_URL = "http://capture-logs.example.com"
_QUERY = 'sum by (service_name, route) (rate(http_requests_total{status=~"5.."}[5m]))'


def _vector(*series: tuple[dict[str, str], str]) -> dict[str, Any]:
    return {
        "status": "success",
        "data": {
            "resultType": "vector",
            "result": [{"metric": labels, "value": [0, value]} for labels, value in series],
        },
    }


def _response(status_code: int, body: dict[str, Any]) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response._content = json.dumps(body).encode()
    return response


def _points(request: ExportMetricsServiceRequest) -> list[tuple[str, str, dict[str, str], float, int]]:
    """(service name, metric name, attributes, value, time in nanoseconds) of every gauge point."""
    points = []
    for resource_metrics in request.resource_metrics:
        resource = {kv.key: kv.value.string_value for kv in resource_metrics.resource.attributes}
        for scope in resource_metrics.scope_metrics:
            for metric in scope.metrics:
                for point in metric.gauge.data_points:
                    points.append(
                        (
                            resource.get("service.name", ""),
                            metric.name,
                            {kv.key: kv.value.string_value for kv in point.attributes},
                            point.as_double,
                            point.time_unix_nano,
                        )
                    )
    return sorted(points, key=lambda point: (point[0], sorted(point[2].items())))


class TestRecordingRuleValidation(SimpleTestCase):
    @parameterized.expand(
        [
            ("no_colon", "http_errors_rate5m", _QUERY),
            ("starts_with_colon", ":http_errors:rate5m", _QUERY),
            ("starts_with_digit", "5xx:http_errors:rate5m", _QUERY),
            ("dot", "job:http.errors:rate5m", _QUERY),
            ("space", "job:http errors:rate5m", _QUERY),
            ("reads_itself", "job:http_errors:rate5m", "sum(job:http_errors:rate5m) * 2"),
            ("empty_query", "job:http_errors:rate5m", "  "),
        ]
    )
    def test_a_rule_that_cannot_record_safely_is_refused(self, _name: str, metric_name: str, query: str) -> None:
        with self.assertRaises(RecordingRuleError):
            validate_rule(metric_name, query)

    def test_a_query_reading_a_longer_name_with_the_same_prefix_is_not_self_reference(self) -> None:
        validate_rule("job:http_errors:rate5m", "sum(job:http_errors:rate5m_total)")


class TestRecordingRuleExport(SimpleTestCase):
    def test_each_series_becomes_a_gauge_point_with_its_labels_at_the_evaluation_instant(self) -> None:
        at = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
        request = export_request(
            "job:http_errors:rate5m",
            [
                RecordedSample(labels={"__name__": "x", "service_name": "checkout", "route": "/pay"}, value=0.5),
                RecordedSample(labels={"service_name": "checkout", "route": "/cart"}, value=1.0),
                RecordedSample(labels={"route": "/health"}, value=2.0),
                RecordedSample(labels={"service_name": "checkout", "route": "/nan"}, value=None),
            ],
            at,
        )

        nanos = int(at.timestamp() * 1e9)
        assert _points(request) == [
            ("", "job:http_errors:rate5m", {"route": "/health"}, 2.0, nanos),
            ("checkout", "job:http_errors:rate5m", {"route": "/cart"}, 1.0, nanos),
            ("checkout", "job:http_errors:rate5m", {"route": "/pay"}, 0.5, nanos),
        ]


class TestRecordingRuleAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.flags = self.enterContext(patch("posthoganalytics.feature_enabled", return_value=True))

    @property
    def url(self) -> str:
        return f"/api/projects/{self.team.id}/metrics/recording_rules/"

    def _create(self, **overrides: Any) -> Any:
        return self.client.post(
            self.url, {"metric_name": "job:http_errors:rate5m", "query": _QUERY, **overrides}, format="json"
        )

    def test_a_rule_is_created_listed_edited_and_deleted(self) -> None:
        created = self._create(description="5xx rate per route")
        assert created.status_code == status.HTTP_201_CREATED, created.json()
        rule = created.json()
        assert rule["metric_name"] == "job:http_errors:rate5m"
        assert rule["enabled"] is True
        assert rule["last_evaluated_at"] is None

        listed = self.client.get(self.url)
        assert [item["id"] for item in listed.json()] == [rule["id"]]

        edited = self.client.patch(f"{self.url}{rule['id']}/", {"enabled": False, "query": "sum(up)"}, format="json")
        assert edited.status_code == status.HTTP_200_OK, edited.json()
        assert (edited.json()["enabled"], edited.json()["query"]) == (False, "sum(up)")

        deleted = self.client.delete(f"{self.url}{rule['id']}/")
        assert deleted.status_code == status.HTTP_204_NO_CONTENT
        assert self.client.get(f"{self.url}{rule['id']}/").status_code == status.HTTP_404_NOT_FOUND

    def test_an_edit_does_not_overwrite_what_an_evaluation_recorded_meanwhile(self) -> None:
        rule = MetricRecordingRule.objects.unscoped().create(team=self.team, metric_name="job:x:rate5m", query=_QUERY)
        stale = MetricRecordingRule.objects.unscoped().get(id=rule.id)
        recorded_at = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
        MetricRecordingRule.objects.unscoped().filter(id=rule.id).update(
            last_evaluated_at=recorded_at, last_series_count=3
        )

        with patch("products.metrics.backend.recording_rules.logic._get", return_value=stale):
            update_rule(self.team.id, str(rule.id), description="edited")

        rule.refresh_from_db()
        assert (rule.description, rule.last_evaluated_at, rule.last_series_count) == ("edited", recorded_at, 3)

    def test_the_metric_name_cannot_change_after_create(self) -> None:
        rule = self._create().json()

        response = self.client.patch(f"{self.url}{rule['id']}/", {"metric_name": "job:other:rate5m"}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()

    def test_a_metric_name_is_recorded_by_one_rule_per_project(self) -> None:
        self._create()

        response = self._create()

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()

    def test_a_project_cannot_go_past_the_rule_limit(self) -> None:
        MetricRecordingRule.objects.unscoped().bulk_create(
            [
                MetricRecordingRule(team=self.team, metric_name=f"job:m{index}:rate5m", query=_QUERY)
                for index in range(MAX_RECORDING_RULES_PER_TEAM)
            ]
        )

        response = self._create()

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()

    def test_a_rule_in_another_project_is_not_found(self) -> None:
        other_team = self.create_team_with_organization(organization=self.organization)
        other = MetricRecordingRule.objects.unscoped().create(team=other_team, metric_name="job:x:rate5m", query=_QUERY)

        assert self.client.get(f"{self.url}{other.id}/").status_code == status.HTTP_404_NOT_FOUND
        assert self.client.get(f"{self.url}{'-' * 36}/").status_code == status.HTTP_404_NOT_FOUND

    def test_a_project_without_the_flag_cannot_use_recording_rules(self) -> None:
        self.flags.side_effect = lambda key, *args, **kwargs: key != "metrics-recording-rules"

        assert self._create().status_code == status.HTTP_403_FORBIDDEN


@override_settings(METRICS_RECORDING_RULES_INGEST_URL=_INGEST_URL, SNUFFLE_APM_URL="http://snuffle.example.com")
class TestRecordingRuleEvaluation(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.now = datetime(2026, 11, 6, 12, 0, 40, tzinfo=UTC)
        self.snuffle = self.enterContext(patch("products.metrics.backend.promql.snuffle_request"))
        self.snuffle.return_value = _response(
            200, _vector(({"service_name": "checkout", "route": "/pay"}, "0.5"), ({"route": "/health"}, "2"))
        )
        self.ingest = MagicMock(return_value=_response(200, {}))
        self.enterContext(patch("products.metrics.backend.recording_rules.otlp.internal_requests.post", self.ingest))
        # Ingestion is five seconds behind the evaluation's clock.
        self.checkpoint = self.enterContext(
            patch(
                "products.metrics.backend.recording_rules.evaluation.fetch_partition_checkpoint",
                side_effect=lambda *args, **kwargs: self.now - timedelta(seconds=5),
            )
        )
        self.flags = self.enterContext(patch("posthoganalytics.feature_enabled", return_value=True))
        self.rule = MetricRecordingRule.objects.unscoped().create(
            team=self.team, metric_name="job:http_errors:rate5m", query=_QUERY
        )

    def _evaluate(self) -> int:
        with team_scope(self.team.id):
            return evaluate_team_recording_rules(self.team.id, self.now)

    def _written(self) -> list[tuple[str, str, dict[str, str], float, int]]:
        (call,) = self.ingest.call_args_list
        request = ExportMetricsServiceRequest()
        request.ParseFromString(call.kwargs["data"])
        return _points(request)

    def test_a_rule_writes_its_result_into_the_project_at_the_minute_ingestion_reached(self) -> None:
        assert self._evaluate() == 1

        at = datetime(2026, 11, 6, 12, 0, 0, tzinfo=UTC)
        assert self.snuffle.call_args.kwargs["data"]["query"] == _QUERY
        assert self.snuffle.call_args.kwargs["data"]["time"] == str(at.timestamp())
        (call,) = self.ingest.call_args_list
        assert call.args[0] == f"{_INGEST_URL}/i/v1/metrics"
        assert call.kwargs["headers"]["Authorization"] == f"Bearer {self.team.api_token}"
        nanos = int(at.timestamp() * 1e9)
        assert self._written() == [
            ("", "job:http_errors:rate5m", {"route": "/health"}, 2.0, nanos),
            ("checkout", "job:http_errors:rate5m", {"route": "/pay"}, 0.5, nanos),
        ]
        self.rule.refresh_from_db()
        assert (self.rule.last_evaluated_at, self.rule.last_series_count, self.rule.last_error) == (at, 2, None)

    def test_a_minute_already_written_is_not_written_again(self) -> None:
        self._evaluate()
        self.ingest.reset_mock()
        self.now += timedelta(seconds=10)

        assert self._evaluate() == 0
        assert self.ingest.call_count == 0

        self.now += timedelta(minutes=1)

        assert self._evaluate() == 1

    @parameterized.expand(
        [
            ("query_error", _response(422, {"status": "error", "error": "parse error at char 3"}), "parse error"),
            (
                "range_vector",
                _response(200, {"status": "success", "data": {"resultType": "matrix", "result": []}}),
                "instant vector",
            ),
            (
                "series_differing_only_by_name",
                _response(
                    200, _vector(({"__name__": "a", "route": "/x"}, "1"), ({"__name__": "b", "route": "/x"}, "2"))
                ),
                "differ only by metric name",
            ),
            (
                "too_many_series",
                _response(200, _vector(*(({"route": f"/{index}"}, "1") for index in range(MAX_SERIES + 1)))),
                "more than",
            ),
        ]
    )
    def test_a_query_that_cannot_be_recorded_keeps_its_error_and_writes_nothing(
        self, _name: str, response: requests.Response, error: str
    ) -> None:
        self.snuffle.return_value = response

        assert self._evaluate() == 0

        assert self.ingest.call_count == 0
        self.rule.refresh_from_db()
        assert error in (self.rule.last_error or "")
        assert self.rule.last_evaluated_at is None

    def test_a_rule_that_keeps_failing_does_not_take_every_turn_from_the_others(self) -> None:
        failing = MetricRecordingRule.objects.unscoped().create(
            team=self.team, metric_name="job:a_failing:rate5m", query=_QUERY
        )
        clock = [0.0]

        def slow_query(*args: Any, **kwargs: Any) -> requests.Response:
            clock[0] += 39
            if kwargs["data"]["query"] == "failing":
                return _response(500, {})
            return _response(200, _vector(({"route": "/a"}, "1")))

        failing.query = "failing"
        failing.save()
        self.snuffle.side_effect = slow_query
        with patch("products.metrics.backend.recording_rules.evaluation.time.monotonic", lambda: clock[0]):
            assert self._evaluate() == 0
            self.now += timedelta(minutes=1)
            assert self._evaluate() == 1

        self.rule.refresh_from_db()
        assert self.rule.last_evaluated_at is not None

    def test_projects_whose_rules_waited_longest_are_evaluated_first(self) -> None:
        other_team = self.create_team_with_organization(organization=self.organization)
        MetricRecordingRule.objects.unscoped().create(team=other_team, metric_name="job:x:rate5m", query=_QUERY)
        MetricRecordingRule.objects.unscoped().filter(id=self.rule.id).update(last_attempted_at=self.now)

        assert teams_with_recording_rules() == [other_team.id, self.team.id]

    def test_nothing_is_recorded_until_ingestion_reports_how_far_it_has_reached(self) -> None:
        self.checkpoint.side_effect = None
        self.checkpoint.return_value = None

        assert self._evaluate() == 0

        assert self.snuffle.call_count == 0
        self.rule.refresh_from_db()
        assert self.rule.last_evaluated_at is None
        assert self.rule.last_error

    def test_a_project_that_loses_the_flag_stops_being_evaluated(self) -> None:
        self.flags.return_value = False

        assert self._evaluate() == 0
        assert self.snuffle.call_count == 0

    def test_a_result_with_nothing_to_write_marks_the_minute_without_a_request(self) -> None:
        self.snuffle.return_value = _response(200, _vector(({"route": "/a"}, "NaN")))

        assert self._evaluate() == 1

        assert self.ingest.call_count == 0
        self.rule.refresh_from_db()
        assert (self.rule.last_evaluated_at, self.rule.last_series_count, self.rule.last_error) == (
            datetime(2026, 11, 6, 12, 0, 0, tzinfo=UTC),
            1,
            None,
        )

    @parameterized.expand(
        [
            ("refused", {"return_value": _response(503, {})}, None),
            ("unreachable", {"side_effect": requests.ConnectionError()}, None),
            ("unconfirmed", {"side_effect": requests.ReadTimeout()}, datetime(2026, 11, 6, 12, 0, 0, tzinfo=UTC)),
        ]
    )
    def test_a_failed_write_keeps_the_minute_due_unless_it_may_have_landed(
        self, _name: str, ingest: dict[str, Any], last_evaluated_at: datetime | None
    ) -> None:
        self.ingest.configure_mock(**ingest)

        assert self._evaluate() == 0

        self.rule.refresh_from_db()
        assert self.rule.last_evaluated_at == last_evaluated_at
        assert self.rule.last_error

    def test_only_enabled_rules_are_evaluated(self) -> None:
        other_team = self.create_team_with_organization(organization=self.organization)
        MetricRecordingRule.objects.unscoped().create(
            team=other_team, metric_name="job:x:rate5m", query=_QUERY, enabled=False
        )
        self.rule.enabled = False
        self.rule.save()

        assert teams_with_recording_rules() == []
        assert self._evaluate() == 0
        assert self.snuffle.call_count == 0

    @override_settings(METRICS_RECORDING_RULES_INGEST_URL="")
    def test_nothing_is_evaluated_without_an_ingest_endpoint(self) -> None:
        assert self._evaluate() == 0
        assert self.snuffle.call_count == 0


async def _run_recording_rules_workflow(team_ids: list[int], failing: set[int]) -> int:
    evaluated: list[int] = []

    @activity.defn(name="find_teams_with_recording_rules_activity")
    async def find(inputs: RecordingRulesInputs) -> list[int]:
        return team_ids

    @activity.defn(name="evaluate_team_recording_rules_activity")
    async def evaluate(inputs: TeamRecordingRulesInputs) -> int:
        if inputs.team_id in failing:
            raise ApplicationError("Snuffle is down", non_retryable=True)
        evaluated.append(inputs.team_id)
        return 1

    async with await WorkflowEnvironment.start_time_skipping() as env:
        task_queue = f"test-{uuid.uuid4()}"
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[MetricsRecordingRulesWorkflow],
            activities=[find, evaluate],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            return await env.client.execute_workflow(
                MetricsRecordingRulesWorkflow.run, RecordingRulesInputs(), id=str(uuid.uuid4()), task_queue=task_queue
            )


@pytest.mark.asyncio
async def test_a_team_whose_rules_fail_does_not_stop_the_other_teams() -> None:
    assert await _run_recording_rules_workflow([1, 2, 3], failing={2}) == 2


def test_recording_rules_schedule_is_registered() -> None:
    assert create_metrics_recording_rules_schedule in schedules
