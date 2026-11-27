"""Tests for the product analytics events of the recalculation flow."""

from datetime import datetime

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from clickhouse_driver.errors import ServerException
from parameterized import parameterized
from temporalio.exceptions import ApplicationError

from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded
from posthog.exceptions import ClickHouseAtCapacity, ClickHouseQueryMemoryLimitExceeded, ClickHouseQueryTimeOut

from products.experiments.backend.models.experiment import (
    Experiment,
    ExperimentMetricsRecalculation,
    ExperimentSavedMetric,
    ExperimentToSavedMetric,
)
from products.experiments.backend.temporal.models import (
    CAPACITY_MAX_METRIC_ATTEMPTS,
    MAX_METRIC_ATTEMPTS,
    RecalculationProgressUpdate,
)
from products.experiments.stats.shared.statistics import StatisticError
from products.feature_flags.backend.models.feature_flag import FeatureFlag

from . import test_helpers


@pytest.mark.django_db(transaction=True)
class TestRecalculationAnalytics(BaseTest):
    """Product analytics emitted by the recalculation activities. Names mirror the legacy client-side
    events; execution_mode='recalculation' distinguishes the backend-driven flow."""

    def _flag(self, key: str) -> FeatureFlag:
        return FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key=key,
            name=f"Flag for {key}",
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

    def _experiment(self, flag_key: str, *, metrics=None, secondary=None) -> Experiment:
        exp = Experiment.objects.create(
            team=self.team,
            created_by=self.user,
            feature_flag=self._flag(flag_key),
            name="exp",
            start_date=timezone.now(),
        )
        if metrics is not None:
            exp.metrics = metrics
        if secondary is not None:
            exp.metrics_secondary = secondary
        exp.save()
        return exp

    def _recalc(self, exp: Experiment, *, metric_uuids: list[str]) -> ExperimentMetricsRecalculation:
        return ExperimentMetricsRecalculation.objects.create(
            team=self.team,
            experiment=exp,
            metric_uuids=metric_uuids,
            total_metrics=len(metric_uuids),
            query_to=datetime.fromisoformat(test_helpers._QUERY_TO),
        )

    @parameterized.expand([("manual",), ("scheduled",)])
    def test_metric_finished_event_on_success(self, trigger: str) -> None:
        exp = self._experiment(flag_key="an-success", metrics=[test_helpers._mean_metric("m1")])
        recalc = self._recalc(exp, metric_uuids=["m1"])
        recalc.trigger = trigger
        recalc.save(update_fields=["trigger"])

        with test_helpers._record_captures() as captured:
            with test_helpers._patched_runner() as mock_runner:
                mock_runner.return_value.run.return_value.model_dump.return_value = {}
                test_helpers._calculate(exp.id, "m1", str(recalc.id), test_helpers._QUERY_TO)

        assert len(captured) == 1
        props = captured[0]["properties"]
        assert captured[0]["event"] == "experiment metric finished"
        assert captured[0]["distinct_id"] == self.user.distinct_id
        assert props["experiment_id"] == exp.id
        assert props["team_id"] == self.team.id
        assert props["metric_uuid"] == "m1"
        assert props["metric_kind"] == "mean"
        assert props["is_primary"] is True
        assert props["execution_mode"] == "recalculation"
        if trigger == "scheduled":
            assert props["$update_person_last_seen_at"] is False
        else:
            assert "$update_person_last_seen_at" not in props
        assert "duration_ms" in props

    def test_metric_error_event_on_insufficient_data(self):
        exp = self._experiment(flag_key="an-error", metrics=[test_helpers._mean_metric("m1")])
        recalc = self._recalc(exp, metric_uuids=["m1"])

        with test_helpers._record_captures() as captured:
            with test_helpers._patched_runner() as mock_runner:
                mock_runner.return_value.run.side_effect = StatisticError("not enough data")
                test_helpers._calculate(exp.id, "m1", str(recalc.id), test_helpers._QUERY_TO)

        assert len(captured) == 1
        props = captured[0]["properties"]
        assert captured[0]["event"] == "experiment metric error"
        assert props["error_type"] == "insufficient_data"
        assert props["error_message"] == "not enough data"
        assert props["execution_mode"] == "recalculation"

    def test_secondary_metric_is_not_marked_primary(self):
        # The workflow passes the role from discovery (ExperimentMetricToRecalculate.role), and the
        # calculation does not look it up again, so the test passes it explicitly to exercise the same path.
        exp = self._experiment(flag_key="an-secondary", secondary=[test_helpers._mean_metric("s1")])
        recalc = self._recalc(exp, metric_uuids=["s1"])

        with test_helpers._record_captures() as captured:
            with test_helpers._patched_runner() as mock_runner:
                mock_runner.return_value.run.return_value.model_dump.return_value = {}
                test_helpers._calculate(exp.id, "s1", str(recalc.id), test_helpers._QUERY_TO, role="secondary")

        assert captured[0]["properties"]["is_primary"] is False

    @parameterized.expand(
        [
            # (name, exc, expected_error_type, expected_delay_seconds, expected_max_attempts, expected_message) —
            # backpressure uses the explicit concurrency delay; a generic transient on attempt 2 follows the policy backoff
            # (5 * 2^1). The generic exception carries a fake credential to lock in that raw exception text
            # (which can embed the executed query, warehouse secrets included) never reaches analytics.
            (
                "backpressure",
                ConcurrencyLimitExceeded("quota"),
                "rate_limited",
                47.5,
                CAPACITY_MAX_METRIC_ATTEMPTS,
                "The query was deferred because the cluster is at capacity.",
            ),
            (
                "generic_transient",
                RuntimeError("blip aws_access_key_id=AKIAFAKESECRET"),
                "server_error",
                10,
                MAX_METRIC_ATTEMPTS,
                "The query failed with a server error.",
            ),
        ]
    )
    def test_non_final_failure_emits_retry_event(
        self,
        name: str,
        exc: Exception,
        expected_error_type: str,
        expected_delay_seconds: float,
        expected_max_attempts: int,
        expected_message: str,
    ):
        # A non-final attempt re-raises for Temporal to retry. It emits 'experiment metric retry' (not
        # 'experiment metric error', which is reserved for the terminal attempt) so retries that later
        # succeed are still countable. Guards against dropping the retry emit, double-counting a
        # non-terminal failure as an error, and leaking the raw exception (secrets included) into analytics.
        exp = self._experiment(flag_key=f"an-retry-{name}", metrics=[test_helpers._mean_metric("m1")])
        recalc = self._recalc(exp, metric_uuids=["m1"])

        with test_helpers._record_captures() as captured:
            with (
                test_helpers._patched_runner() as mock_runner,
                patch(
                    "products.experiments.backend.temporal.recalculation.attempt_records.random.uniform",
                    return_value=47.5,
                ),
            ):
                mock_runner.return_value.run.side_effect = exc
                with pytest.raises((type(exc), ApplicationError)):
                    test_helpers._calculate(
                        exp.id, "m1", str(recalc.id), test_helpers._QUERY_TO, is_final_attempt=False, attempt=2
                    )

        assert len(captured) == 1
        assert captured[0]["event"] == "experiment metric retry"
        props = captured[0]["properties"]
        assert props["error_type"] == expected_error_type
        assert props["error_message"] == expected_message
        assert "AKIAFAKESECRET" not in props["error_message"]
        assert props["attempt"] == 2
        assert props["max_attempts"] == expected_max_attempts
        assert props["next_retry_delay_seconds"] == expected_delay_seconds
        assert props["execution_mode"] == "recalculation"
        assert props["mechanism"] == "orchestrated"

    @parameterized.expand(
        [
            # name, exc, expected_error_type, raises_application_error
            # Permanent classes (oom/byte_limit/validation) and backpressure (at_capacity) re-raise as
            # ApplicationError; genuinely transient classes re-raise the original exception for Temporal.
            ("wrapped_oom", ClickHouseQueryMemoryLimitExceeded(), "out_of_memory", True),
            ("wrapped_timeout", ClickHouseQueryTimeOut(), "timeout", False),
            ("wrapped_at_capacity", ClickHouseAtCapacity(), "rate_limited", True),
            ("ch_timeout_code", ServerException("timed out", code=159), "timeout", False),
            ("ch_socket_timeout_code", ServerException("socket timed out", code=209), "timeout", False),
            ("ch_memory_limit_code", ServerException("memory limit exceeded", code=241), "out_of_memory", True),
            ("ch_too_many_bytes_code", ServerException("too many bytes", code=307), "byte_limit", True),
            ("ch_too_many_queries_code", ServerException("too many queries", code=202), "rate_limited", False),
            ("other", RuntimeError("kaboom"), "server_error", False),
        ]
    )
    def test_terminal_failure_emits_metric_error_event(self, name, exc, expected_error_type, raises_application_error):
        # On the terminal attempt (retries exhausted) an infra failure emits 'experiment metric error'
        # with the shared backend error_type taxonomy — including byte_limit (307) and rate_limited (202),
        # the two real failure modes that used to collapse into server_error and stay invisible.
        exp = self._experiment(flag_key=f"an-terminal-{name}", metrics=[test_helpers._mean_metric("m1")])
        recalc = self._recalc(exp, metric_uuids=["m1"])

        with test_helpers._record_captures() as captured:
            with test_helpers._patched_runner() as mock_runner:
                mock_runner.return_value.run.side_effect = exc
                with pytest.raises(ApplicationError if raises_application_error else type(exc)):
                    test_helpers._calculate(exp.id, "m1", str(recalc.id), test_helpers._QUERY_TO, is_final_attempt=True)

        assert len(captured) == 1
        assert captured[0]["event"] == "experiment metric error"
        props = captured[0]["properties"]
        assert props["error_type"] == expected_error_type
        assert props["execution_mode"] == "recalculation"
        assert props["context"] == "ui"
        assert props["mechanism"] == "orchestrated"
        assert props["trigger"] == "manual"

    @parameterized.expand([("manual",), ("scheduled",)])
    def test_results_refresh_completed_event_on_finish(self, trigger: str) -> None:
        exp = self._experiment(
            flag_key="an-finish", metrics=[test_helpers._mean_metric("m1")], secondary=[test_helpers._mean_metric("s1")]
        )
        for uuid, role in [("sp1", "primary"), ("ss1", "secondary")]:
            saved = ExperimentSavedMetric.objects.create(
                team=self.team, name=f"saved-{uuid}", query=test_helpers._mean_metric(uuid)
            )
            ExperimentToSavedMetric.objects.create(experiment=exp, saved_metric=saved, metadata={"type": role})
        recalc = self._recalc(exp, metric_uuids=["m1", "s1", "sp1", "ss1"])
        recalc.trigger = trigger
        recalc.save(update_fields=["trigger"])

        with test_helpers._record_captures() as captured:
            test_helpers._update(
                RecalculationProgressUpdate(
                    recalculation_id=str(recalc.id),
                    status="completed",
                    mark_completed=True,
                    succeeded_metrics=3,
                    failed_metrics=1,
                )
            )

        assert len(captured) == 1
        props = captured[0]["properties"]
        assert captured[0]["event"] == "experiment results refresh completed"
        assert captured[0]["distinct_id"] == self.user.distinct_id
        assert props["experiment_id"] == exp.id
        assert props["team_id"] == self.team.id
        assert props["recalculation_id"] == str(recalc.id)
        assert props["status"] == "completed"
        assert props["succeeded_metrics"] == 3
        assert props["failed_metrics"] == 1
        assert props["primary_metrics_count"] == 2
        assert props["secondary_metrics_count"] == 2
        assert props["execution_mode"] == "recalculation"
        if trigger == "scheduled":
            assert props["$update_person_last_seen_at"] is False
        else:
            assert "$update_person_last_seen_at" not in props
        assert "total_duration_ms" in props

    def test_results_refresh_completed_not_re_emitted_on_retry(self):
        # mark_completed is first-write-wins; a retried finish activity must not re-fire the run-level event.
        exp = self._experiment(flag_key="an-finish-retry", metrics=[test_helpers._mean_metric("m1")])
        recalc = self._recalc(exp, metric_uuids=["m1"])

        update = RecalculationProgressUpdate(
            recalculation_id=str(recalc.id), status="completed", mark_completed=True, succeeded_metrics=1
        )
        with test_helpers._record_captures() as captured:
            test_helpers._update(update)
            test_helpers._update(update)  # simulated Temporal retry

        assert len(captured) == 1
