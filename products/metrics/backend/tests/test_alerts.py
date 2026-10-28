import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from django.utils import timezone

import requests
from parameterized import parameterized
from pydantic import ValidationError
from rest_framework import status

from posthog.models.scoping import team_scope

from products.alerts_platform.backend.facade import testing as platform_testing
from products.alerts_platform.backend.facade.api import create_configuration, record_outcomes, slot_of
from products.alerts_platform.backend.facade.contracts import (
    AlertEventKind,
    Grouping,
    GroupingMode,
    PlatformAlertConfigurationEdit,
    PlatformAlertOutcome,
    SourceKind,
)
from products.metrics.backend.alerts.checkpoint import evaluation_time
from products.metrics.backend.alerts.evaluation import evaluate_metrics_alert_batch
from products.metrics.backend.alerts.source_config import MetricsPlatformAlertConfig

_QUERY = 'sum(kafka_consumer_group_lag{group="example"})'


class TestMetricsAlertConfig(SimpleTestCase):
    @parameterized.expand(
        [
            ("threshold_without_operator", {"query": _QUERY, "condition": {"threshold": 10}}),
            ("threshold_without_value", {"query": _QUERY, "condition": {"operator": ">"}}),
            ("present_with_threshold", {"query": _QUERY, "condition": {"kind": "present", "threshold": 1}}),
            ("empty_query", {"query": "", "condition": {"kind": "present"}}),
            ("unknown_operator", {"query": _QUERY, "condition": {"operator": "above", "threshold": 1}}),
            ("nan_threshold", {"query": _QUERY, "condition": {"operator": ">", "threshold": float("nan")}}),
        ]
    )
    def test_a_config_that_cannot_be_evaluated_is_refused(self, _name: str, config: dict[str, object]) -> None:
        with self.assertRaises(ValidationError):
            MetricsPlatformAlertConfig.model_validate(config)


class TestMetricsAlertCreate(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(patch("posthoganalytics.feature_enabled", return_value=True))

    def _create(self, source_config: dict[str, object]) -> Any:
        return self.client.post(
            f"/api/projects/{self.team.id}/platform_alerts/",
            {"source_kind": "metrics", "name": "Consumer lag", "enabled": True, "source_config": source_config},
            format="json",
        )

    def test_a_metrics_alert_is_created_through_the_platform_api(self) -> None:
        response = self._create({"query": _QUERY, "condition": {"operator": ">", "threshold": 1000}})

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert response.json()["source_kind"] == "metrics"
        assert response.json()["check_interval_minutes"] == 1


class TestEvaluationTime(SimpleTestCase):
    @parameterized.expand(
        [
            ("fresh_checkpoint_holds_the_check_back", timedelta(seconds=-30), timedelta(seconds=-30)),
            ("stale_checkpoint_is_ignored", timedelta(minutes=-6), timedelta(0)),
            ("checkpoint_past_the_due_time", timedelta(seconds=30), timedelta(0)),
            ("no_checkpoint", None, timedelta(0)),
        ]
    )
    def test_a_check_reads_no_later_than_ingestion_reached(
        self, _name: str, checkpoint_offset: timedelta | None, expected_offset: timedelta
    ) -> None:
        due_at = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        checkpoint = None if checkpoint_offset is None else due_at + checkpoint_offset

        assert evaluation_time(due_at, checkpoint) == due_at + expected_offset


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


class TestMetricsAlertEvaluation(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.cutoff = timezone.now().replace(second=0, microsecond=0) + timedelta(minutes=5)
        self.snuffle = MagicMock()
        self.enterContext(patch("products.metrics.backend.promql.snuffle_request", self.snuffle))
        self.checkpoint = self.enterContext(
            patch("products.metrics.backend.alerts.evaluation.fetch_live_metrics_checkpoint", return_value=None)
        )
        with team_scope(self.team.id):
            self.configuration_id = create_configuration(
                team_id=self.team.id,
                source_kind=SourceKind.METRICS,
                edit=PlatformAlertConfigurationEdit(
                    name="Consumer lag",
                    enabled=True,
                    source_config={"query": _QUERY, "condition": {"operator": ">", "threshold": 1000}},
                    grouping=Grouping(mode=GroupingMode.BY_RESULT_LABELS, keys=("group",)),
                    schedule_restriction=None,
                    evaluation_periods=1,
                    datapoints_to_alarm=1,
                    cooldown_minutes=0,
                ),
                created_by_id=self.user.id,
            ).id
            platform_testing.set_due_at(self.configuration_id, self.due_at)

    @property
    def due_at(self) -> datetime:
        return self.cutoff - timedelta(minutes=1)

    def _evaluate(self) -> PlatformAlertOutcome:
        with team_scope(self.team.id):
            evaluation = evaluate_metrics_alert_batch(self.team.id, slot_of(self.due_at, self.cutoff), self.cutoff)
        (outcome,) = evaluation.outcomes
        return outcome

    def _next_check(self, outcome: PlatformAlertOutcome) -> None:
        with team_scope(self.team.id):
            record_outcomes(self.team.id, [outcome], self.cutoff)
            self.cutoff += timedelta(minutes=5)
            platform_testing.set_due_at(self.configuration_id, self.due_at)

    def _kinds(self, outcome: PlatformAlertOutcome) -> dict[str, AlertEventKind]:
        return {json.loads(group.grouping_key)["group"]: group.kind for group in outcome.groups}

    def test_a_series_fires_resolves_when_it_vanishes_and_holds_when_it_has_no_number(self) -> None:
        self.checkpoint.return_value = self.due_at - timedelta(seconds=30)
        self.snuffle.return_value = _response(
            200, _vector(({"group": "a"}, "2000"), ({"group": "b"}, "3000"), ({"group": "c"}, "10"))
        )
        first = self._evaluate()

        assert self._kinds(first) == {"a": AlertEventKind.FIRING, "b": AlertEventKind.FIRING}
        assert self.snuffle.call_args.kwargs["data"]["time"] == str((self.due_at - timedelta(seconds=30)).timestamp())

        self._next_check(first)
        self.snuffle.return_value = _response(
            200, _vector(({"group": "b"}, "NaN"), ({"group": "b"}, "10"), ({"group": "c"}, "10"))
        )

        assert self._kinds(self._evaluate()) == {"a": AlertEventKind.RESOLVED}

    @parameterized.expand(
        [
            ("rejected_query_counts_toward_broken", _response(400, {"status": "error", "error": "parse error"}), 1),
            ("backend_failure_is_transient", _response(503, {"status": "error"}), 0),
            ("timeout_is_transient", requests.Timeout(), 0),
            (
                "too_many_series_counts_toward_broken",
                _response(200, _vector(*(({"group": str(index)}, "1") for index in range(1001)))),
                1,
            ),
        ]
    )
    def test_a_failed_query_records_a_failure(
        self, _name: str, result: requests.Response | Exception, consecutive_failures: int
    ) -> None:
        if isinstance(result, Exception):
            self.snuffle.side_effect = result
        else:
            self.snuffle.return_value = result

        outcome = self._evaluate()

        assert outcome.failure is not None
        assert (outcome.configuration_id, outcome.consecutive_failures) == (
            UUID(str(self.configuration_id)),
            consecutive_failures,
        )
