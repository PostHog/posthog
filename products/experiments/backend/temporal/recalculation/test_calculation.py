"""Tests for the calculation of one metric, its query cancel and its out-of-time failure."""

from datetime import datetime, timedelta

import pytest
import time_machine
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import override_settings
from django.utils import timezone

from clickhouse_driver.errors import ServerException
from parameterized import parameterized
from rest_framework.exceptions import ValidationError
from temporalio.exceptions import ApplicationError

from posthog.schema import PrecomputationMode

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import ClickHouseUser, Workload
from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded
from posthog.clickhouse.query_tagging import Feature, Product, get_query_tags, tags_context
from posthog.exceptions import ClickHouseAtCapacity, ClickHouseQueryMemoryLimitExceeded, ClickHouseQueryTimeOut
from posthog.models.team.extensions import get_or_create_team_extension
from posthog.temporal.common.errors import NonReportableError

from products.experiments.backend.facade.enums import ExposuresPath
from products.experiments.backend.hogql_queries.experiment_query_runner import ExperimentQueryRunner
from products.experiments.backend.metric_calculation.config import get_metric_calculation_config
from products.experiments.backend.metric_calculation.results import _recalc_fingerprint
from products.experiments.backend.models.experiment import (
    Experiment,
    ExperimentMetricResult,
    ExperimentMetricsRecalculation,
    ExperimentSavedMetric,
    ExperimentToSavedMetric,
)
from products.experiments.backend.models.team_experiments_config import TeamExperimentsConfig
from products.experiments.backend.recalculation.payloads import build_job_payload, get_run_results
from products.experiments.backend.temporal.models import (
    CAPACITY_MAX_METRIC_ATTEMPTS,
    MAX_METRIC_ATTEMPTS,
    TIMEOUT_MAX_METRIC_ATTEMPTS,
    MetricOutOfTimeFailure,
)
from products.experiments.backend.temporal.recalculation.calculation import (
    _cancel_metric_query_sync,
    _record_metric_out_of_time_failure_sync,
)
from products.experiments.backend.test.utils import patch_calculation_key_version
from products.experiments.stats.shared.statistics import StatisticError
from products.feature_flags.backend.models.feature_flag import FeatureFlag

from . import test_helpers

_cancel_raw = _cancel_metric_query_sync.func  # type: ignore[attr-defined]

_record_out_of_time_raw = _record_metric_out_of_time_failure_sync.func  # type: ignore[attr-defined]


def _calculation_key(experiment: Experiment, metric_uuid: str) -> str:
    calculation_config = get_metric_calculation_config(experiment, metric_uuid)
    assert calculation_config is not None
    return calculation_config.calculation_key()


def _record_out_of_time(failure: MetricOutOfTimeFailure) -> None:
    with patch("products.experiments.backend.temporal.recalculation.calculation.close_old_connections"):
        _record_out_of_time_raw(failure)


@pytest.mark.django_db(transaction=True)
class TestCalculateActivity(BaseTest):
    def _flag(self, key: str) -> FeatureFlag:
        return FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key=key,
            name=f"Flag for {key}",
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {"key": "control", "name": "Control", "rollout_percentage": 50},
                        {"key": "test", "name": "Test", "rollout_percentage": 50},
                    ]
                },
            },
        )

    def _experiment(self, flag_key: str, *, with_start_date: bool = True, metrics=None) -> Experiment:
        exp = Experiment.objects.create(
            team=self.team,
            created_by=self.user,
            feature_flag=self._flag(flag_key),
            name="exp",
            start_date=timezone.now() if with_start_date else None,
        )
        if metrics is not None:
            exp.metrics = metrics
            exp.save()
        return exp

    def _recalc(
        self, exp: Experiment, *, metric_uuids: list[str], total: int | None = None
    ) -> ExperimentMetricsRecalculation:
        """Create a recalc row in the post-discovery + post-start state, so the calculate activity's
        input-validation guards (metric_uuids membership, query_to set) are satisfied as the workflow
        would have set them."""
        return ExperimentMetricsRecalculation.objects.create(
            team=self.team,
            experiment=exp,
            metric_uuids=metric_uuids,
            total_metrics=total if total is not None else len(metric_uuids),
            query_to=datetime.fromisoformat(test_helpers._QUERY_TO),
        )

    def test_metric_disappeared_between_discovery_and_calc(self):
        # Discovery included m1 in the recalc's metric set (so input validation passes), but the experiment
        # was edited and m1 is no longer present — the calc activity's inner lookup must surface this as a
        # discovery-step failure rather than crashing.
        exp = self._experiment(flag_key="calc-missing", metrics=[])
        recalc = self._recalc(exp, metric_uuids=["m1"])

        result = test_helpers._calculate(exp.id, "m1", str(recalc.id), test_helpers._QUERY_TO)

        assert result.success is False
        assert result.error_step == "discovery"
        recalc.refresh_from_db()
        assert len(recalc.metric_errors) == 1
        assert recalc.metric_errors["m1"]["error_type"] == "validation_error"
        assert recalc.metric_errors["m1"]["retriable"] is False
        assert recalc.metric_errors["m1"]["calculation_key"] is None

    def test_bad_metric_type_fails_at_calculation(self):
        # An unknown metric_type is unschedulable, so the calc lookup fails the metric permanently
        # instead of raising KeyError while building it.
        exp = self._experiment(
            flag_key="calc-badtype",
            metrics=[{"uuid": "m-bad", "metric_type": "nonsense", "kind": "ExperimentMetric"}],
        )
        recalc = self._recalc(exp, metric_uuids=["m-bad"])

        result = test_helpers._calculate(exp.id, "m-bad", str(recalc.id), test_helpers._QUERY_TO)

        assert result.success is False
        recalc.refresh_from_db()
        assert len(recalc.metric_errors) == 1
        assert "m-bad" in recalc.metric_errors

    def test_missing_start_date_fails(self):
        exp = self._experiment(
            flag_key="calc-no-start", with_start_date=False, metrics=[test_helpers._mean_metric("m1")]
        )
        recalc = self._recalc(exp, metric_uuids=["m1"])

        result = test_helpers._calculate(exp.id, "m1", str(recalc.id), test_helpers._QUERY_TO)

        assert result.success is False
        recalc.refresh_from_db()
        assert len(recalc.metric_errors) == 1

    def test_saved_metric_is_resolvable(self):
        # A saved/shared metric (uuid only on saved_metric.query) must be found by the calc lookup; otherwise it
        # would wrongly fail at the discovery step. We force a calculation error so the run reaches the metric via
        # the saved-metric branch but fails for a non-lookup reason. The runtime error is re-raised so Temporal
        # can retry; the failure is recorded to metric_errors first.
        exp = self._experiment(flag_key="calc-saved")
        saved = ExperimentSavedMetric.objects.create(
            team=self.team,
            name="saved-s1",
            query=test_helpers._mean_metric("s1"),
        )
        ExperimentToSavedMetric.objects.create(experiment=exp, saved_metric=saved, metadata={"type": "primary"})
        recalc = self._recalc(exp, metric_uuids=["s1"])

        with test_helpers._patched_runner() as mock_runner:
            mock_runner.return_value.run.side_effect = RuntimeError("kaboom")
            with pytest.raises(RuntimeError, match="kaboom"):
                test_helpers._calculate(exp.id, "s1", str(recalc.id), test_helpers._QUERY_TO)

        # Found the saved metric (did not fail at discovery), failure was recorded before re-raise.
        recalc.refresh_from_db()
        assert "s1" in recalc.metric_errors

    def test_transient_failure_is_not_persisted_until_the_final_attempt(self):
        # A retryable (transient) failure on a non-final attempt re-raises for Temporal to retry but must NOT
        # persist a FAILED row or a metric_errors entry, so the frontend keeps the metric loading instead of
        # flashing an error for a failure that may still succeed. The final attempt persists it.
        exp = self._experiment(flag_key="calc-transient", metrics=[test_helpers._mean_metric("m1")])
        recalc = self._recalc(exp, metric_uuids=["m1"])

        with test_helpers._patched_runner() as mock_runner:
            mock_runner.return_value.run.side_effect = RuntimeError("transient blip")

            # Non-final attempt: re-raises, but nothing is recorded.
            with pytest.raises(RuntimeError, match="transient blip"):
                test_helpers._calculate(exp.id, "m1", str(recalc.id), test_helpers._QUERY_TO, is_final_attempt=False)
            recalc.refresh_from_db()
            assert recalc.metric_errors == {}
            assert not ExperimentMetricResult.objects.filter(experiment=exp, metric_uuid="m1").exists()

            # Final attempt: now the failure is persisted for the UI.
            with pytest.raises(RuntimeError, match="transient blip"):
                test_helpers._calculate(exp.id, "m1", str(recalc.id), test_helpers._QUERY_TO, is_final_attempt=True)
            recalc.refresh_from_db()
            assert "m1" in recalc.metric_errors

    @parameterized.expand(
        [
            # (name, exc, attempt, expected_error_type, expected_delay_seconds, expected_max_attempts,
            # expected_message) — backpressure uses the explicit next_retry_delay; a generic transient on
            # attempt 2 follows the policy backoff (5 * 2^1). The generic exception carries a fake credential
            # to lock in that raw exception text (which can embed the executed query, warehouse secrets
            # included) never reaches the API field.
            (
                "backpressure",
                ConcurrencyLimitExceeded("quota"),
                2,
                "rate_limited",
                47.5,
                CAPACITY_MAX_METRIC_ATTEMPTS,
                "The query was deferred because the cluster is at capacity.",
            ),
            (
                "generic_transient",
                RuntimeError("blip aws_access_key_id=AKIAFAKESECRET"),
                2,
                "server_error",
                10,
                MAX_METRIC_ATTEMPTS,
                "The query failed with a server error.",
            ),
            (
                "timeout",
                ClickHouseQueryTimeOut(),
                1,
                "timeout",
                5,
                TIMEOUT_MAX_METRIC_ATTEMPTS,
                "The query timed out.",
            ),
        ]
    )
    @time_machine.travel("2026-05-29T13:00:00Z", tick=False)
    def test_transient_attempt_records_retry_state_and_success_clears_it(
        self,
        name: str,
        exc: Exception,
        attempt: int,
        expected_error_type: str,
        expected_delay_seconds: float,
        expected_max_attempts: int,
        expected_message: str,
    ):
        # The retry entry is what the UI shows between attempts; without it the metric looks stuck. It must
        # carry the attempt counters and a next_retry_at estimate, and vanish once the metric resolves.
        exp = self._experiment(flag_key=f"calc-retry-{name}", metrics=[test_helpers._mean_metric("m1")])
        recalc = self._recalc(exp, metric_uuids=["m1"])

        with (
            test_helpers._patched_runner() as mock_runner,
            patch(
                "products.experiments.backend.temporal.recalculation.attempt_records.random.uniform", return_value=47.5
            ),
        ):
            mock_runner.return_value.run.side_effect = exc
            with pytest.raises((type(exc), ApplicationError)):
                test_helpers._calculate(
                    exp.id, "m1", str(recalc.id), test_helpers._QUERY_TO, is_final_attempt=False, attempt=attempt
                )

        recalc.refresh_from_db()
        entry = recalc.metric_retries["m1"]
        assert entry["attempt"] == attempt
        assert entry["max_attempts"] == expected_max_attempts
        assert entry["error_type"] == expected_error_type
        assert entry["message"] == expected_message
        assert "AKIAFAKESECRET" not in entry["message"]
        assert entry["calculation_key"] == _calculation_key(exp, "m1")
        next_retry_at = datetime.fromisoformat(entry["next_retry_at"])
        assert (next_retry_at - timezone.now()).total_seconds() == expected_delay_seconds

        with test_helpers._patched_runner() as mock_runner:
            mock_runner.return_value.run.return_value.model_dump.return_value = {}
            result = test_helpers._calculate(exp.id, "m1", str(recalc.id), test_helpers._QUERY_TO, attempt=attempt + 1)

        assert result.success is True
        recalc.refresh_from_db()
        assert recalc.metric_retries == {}

    @parameterized.expand(
        [
            # A transient error that used its final attempt: a heal or manual retry can still succeed.
            ("exhausted_transient", RuntimeError("transient blip"), "server_error", True),
            # Permanent errors stop on the first attempt and need a config or data change first.
            ("validation", ValidationError("bad hogql"), "validation_error", False),
            ("value_error", ValueError("bad metric"), "server_error", False),
        ]
    )
    def test_terminal_failure_records_error_type_and_retriability(
        self, name: str, exc: Exception, expected_error_type: str, expected_retriable: bool
    ):
        exp = self._experiment(flag_key=f"calc-terminal-{name}", metrics=[test_helpers._mean_metric("m1")])
        recalc = self._recalc(exp, metric_uuids=["m1"])

        with test_helpers._patched_runner() as mock_runner:
            mock_runner.return_value.run.side_effect = exc
            mock_runner.return_value.exposures_path = ExposuresPath.DIRECT_SCAN
            with pytest.raises(Exception):
                test_helpers._calculate(exp.id, "m1", str(recalc.id), test_helpers._QUERY_TO, is_final_attempt=True)

        recalc.refresh_from_db()
        entry = recalc.metric_errors["m1"]
        assert entry["error_type"] == expected_error_type
        assert entry["retriable"] is expected_retriable
        assert entry["exposures_path"] == "direct_scan"
        assert entry["calculation_key"] == _calculation_key(exp, "m1")

    def test_terminal_failure_clears_retry_state(self):
        # A metric that retried and then failed for good must not keep a stale "retrying" entry alongside
        # its terminal error.
        exp = self._experiment(flag_key="calc-retry-terminal", metrics=[test_helpers._mean_metric("m1")])
        recalc = self._recalc(exp, metric_uuids=["m1"])

        with test_helpers._patched_runner() as mock_runner:
            mock_runner.return_value.run.side_effect = RuntimeError("transient blip")
            with pytest.raises(RuntimeError):
                test_helpers._calculate(
                    exp.id, "m1", str(recalc.id), test_helpers._QUERY_TO, is_final_attempt=False, attempt=2
                )
            recalc.refresh_from_db()
            assert "m1" in recalc.metric_retries

            with pytest.raises(RuntimeError):
                test_helpers._calculate(
                    exp.id, "m1", str(recalc.id), test_helpers._QUERY_TO, is_final_attempt=True, attempt=8
                )

        recalc.refresh_from_db()
        assert recalc.metric_retries == {}
        assert "m1" in recalc.metric_errors

    @parameterized.expand(
        [
            ("not_persisted_by_any_attempt", RuntimeError("transient blip"), False),
            ("persisted_by_final_attempt", RuntimeError("transient blip"), True),
            # The last attempt wrote its result but died before it reported success.
            ("completed_by_last_attempt", None, False),
        ]
    )
    def test_out_of_time_failure_persists_once(
        self, name: str, last_attempt_error: Exception | None, final_attempt_persisted: bool
    ):
        exp = self._experiment(flag_key=f"calc-out-of-time-{name}", metrics=[test_helpers._mean_metric("m1")])
        recalc = self._recalc(exp, metric_uuids=["m1"])
        with test_helpers._patched_runner() as mock_runner:
            if last_attempt_error is None:
                mock_runner.return_value.run.return_value.model_dump.return_value = {}
                test_helpers._calculate(
                    exp.id, "m1", str(recalc.id), test_helpers._QUERY_TO, is_final_attempt=False, attempt=2
                )
            else:
                mock_runner.return_value.run.side_effect = last_attempt_error
                with pytest.raises(RuntimeError):
                    test_helpers._calculate(
                        exp.id,
                        "m1",
                        str(recalc.id),
                        test_helpers._QUERY_TO,
                        is_final_attempt=final_attempt_persisted,
                        attempt=2,
                    )
        recalc.refresh_from_db()
        errors_before = dict(recalc.metric_errors)

        with test_helpers._record_captures() as captured:
            _record_out_of_time(
                MetricOutOfTimeFailure(
                    recalculation_id=str(recalc.id), experiment_id=exp.id, metric_uuid="m1", role="primary"
                )
            )

        recalc.refresh_from_db()
        row = ExperimentMetricResult.objects.get(experiment=exp, metric_uuid="m1")
        assert row.fingerprint == _recalc_fingerprint(_calculation_key(exp, "m1"))
        assert recalc.metric_retries == {}
        if last_attempt_error is None:
            assert row.status == ExperimentMetricResult.Status.COMPLETED
            assert recalc.metric_errors == {}
            assert captured == []
        elif final_attempt_persisted:
            assert row.status == ExperimentMetricResult.Status.FAILED
            assert recalc.metric_errors == errors_before
            assert captured == []
        else:
            assert row.status == ExperimentMetricResult.Status.FAILED
            assert recalc.metric_errors["m1"]["error_type"] == "timeout"
            assert recalc.metric_errors["m1"]["retriable"] is True
            assert recalc.metric_errors["m1"]["calculation_key"] == _calculation_key(exp, "m1")
            assert [c["event"] for c in captured] == ["experiment metric error"]
            assert captured[0]["properties"]["error_type"] == "timeout"

    def test_late_result_after_out_of_time_failure_replaces_the_timeout(self):
        exp = self._experiment(flag_key="calc-out-of-time-late-result", metrics=[test_helpers._mean_metric("m1")])
        recalc = self._recalc(exp, metric_uuids=["m1"])
        _record_out_of_time(
            MetricOutOfTimeFailure(
                recalculation_id=str(recalc.id), experiment_id=exp.id, metric_uuid="m1", role="primary"
            )
        )

        with test_helpers._patched_runner() as mock_runner:
            mock_runner.return_value.run.return_value.model_dump.return_value = {}
            result = test_helpers._calculate(
                exp.id, "m1", str(recalc.id), test_helpers._QUERY_TO, is_final_attempt=False, attempt=3
            )

        recalc.refresh_from_db()
        assert result.success is True
        assert ExperimentMetricResult.objects.get(experiment=exp, metric_uuid="m1").status == (
            ExperimentMetricResult.Status.COMPLETED
        )
        assert recalc.metric_errors == {}

    @parameterized.expand(
        [
            ("org_quota", ConcurrencyLimitExceeded("org quota saturated")),
            ("cluster_at_capacity", ClickHouseAtCapacity()),
        ]
    )
    def test_backpressure_bounce_defers_with_retry_delay_and_no_capture(self, name: str, exc: Exception):
        # A query bouncing off the per-org ClickHouse limiter or the cluster's at-capacity guard is
        # backpressure, not a fault: it must re-raise as an ApplicationError carrying next_retry_delay
        # (overriding the retry policy's 5s schedule with the capacity backoff band), must never
        # reach capture_exception (a saturated org would spam error tracking with expected bounces), and must
        # persist nothing before the final attempt.
        exp = self._experiment(flag_key=f"calc-quota-{name}", metrics=[test_helpers._mean_metric("m1")])
        recalc = self._recalc(exp, metric_uuids=["m1"])

        with (
            test_helpers._patched_runner() as mock_runner,
            patch("products.experiments.backend.temporal.recalculation.calculation.capture_exception") as mock_capture,
            patch(
                "products.experiments.backend.temporal.recalculation.attempt_records.random.uniform", return_value=47.5
            ),
        ):
            mock_runner.return_value.run.side_effect = exc

            with pytest.raises(ApplicationError) as exc_info:
                test_helpers._calculate(exp.id, "m1", str(recalc.id), test_helpers._QUERY_TO, is_final_attempt=False)
            assert exc_info.value.type == type(exc).__name__
            assert exc_info.value.next_retry_delay == timedelta(seconds=47.5)
            mock_capture.assert_not_called()
            recalc.refresh_from_db()
            assert recalc.metric_errors == {}
            assert not ExperimentMetricResult.objects.filter(experiment=exp, metric_uuid="m1").exists()

            # Final attempt: the failure is persisted for the UI, still without exception capture.
            with pytest.raises(ApplicationError):
                test_helpers._calculate(exp.id, "m1", str(recalc.id), test_helpers._QUERY_TO, is_final_attempt=True)
            mock_capture.assert_not_called()
            recalc.refresh_from_db()
            assert "m1" in recalc.metric_errors
            row = ExperimentMetricResult.objects.get(experiment=exp, metric_uuid="m1")
            assert row.status == ExperimentMetricResult.Status.FAILED

    @parameterized.expand(
        [
            ("capacity", ClickHouseAtCapacity(), CAPACITY_MAX_METRIC_ATTEMPTS, "rate_limited"),
            ("timeout", ClickHouseQueryTimeOut(), TIMEOUT_MAX_METRIC_ATTEMPTS, "timeout"),
        ]
    )
    def test_error_class_cap_fails_the_metric_before_the_policy_limit(
        self, name: str, exc: Exception, cap: int, expected_error_type: str
    ):
        exp = self._experiment(flag_key=f"calc-class-cap-{name}", metrics=[test_helpers._mean_metric("m1")])
        recalc = self._recalc(exp, metric_uuids=["m1"])

        with test_helpers._patched_runner() as mock_runner:
            mock_runner.return_value.run.side_effect = exc
            with pytest.raises((type(exc), ApplicationError)):
                test_helpers._calculate(
                    exp.id, "m1", str(recalc.id), test_helpers._QUERY_TO, is_final_attempt=False, attempt=cap - 1
                )
            recalc.refresh_from_db()
            assert "m1" in recalc.metric_retries
            assert recalc.metric_errors == {}

            with pytest.raises(ApplicationError) as exc_info:
                test_helpers._calculate(
                    exp.id, "m1", str(recalc.id), test_helpers._QUERY_TO, is_final_attempt=False, attempt=cap
                )

        assert exc_info.value.non_retryable is True
        recalc.refresh_from_db()
        assert recalc.metric_retries == {}
        assert recalc.metric_errors["m1"]["error_type"] == expected_error_type
        assert recalc.metric_errors["m1"]["retriable"] is True
        row = ExperimentMetricResult.objects.get(experiment=exp, metric_uuid="m1")
        assert row.status == ExperimentMetricResult.Status.FAILED

    @parameterized.expand(
        [
            ("out_of_memory", ClickHouseQueryMemoryLimitExceeded(), "out_of_memory"),
            ("byte_limit", ServerException("too many bytes", code=307), "byte_limit"),
            ("validation_error", ValidationError("bad metric config"), "validation_error"),
            ("config_value_error", ValueError("Multiple control variants found"), "server_error"),
        ]
    )
    def test_permanent_error_fails_non_retryable_and_persists_on_first_attempt(
        self, name: str, exc: Exception, expected_type: str
    ):
        # Deterministic failures (out-of-memory, byte limits, invalid config) can't succeed on retry, so
        # even a NON-final attempt must persist the FAILED row immediately and raise non_retryable — every
        # retry would burn a full ClickHouse query without changing the outcome.
        exp = self._experiment(flag_key=f"calc-permanent-{name}", metrics=[test_helpers._mean_metric("m1")])
        recalc = self._recalc(exp, metric_uuids=["m1"])

        with test_helpers._patched_runner() as mock_runner:
            mock_runner.return_value.run.side_effect = exc

            with pytest.raises(ApplicationError) as exc_info:
                test_helpers._calculate(exp.id, "m1", str(recalc.id), test_helpers._QUERY_TO, is_final_attempt=False)

        assert exc_info.value.non_retryable is True
        assert exc_info.value.type == expected_type
        # Validation errors are user config, not defects: the raised error must carry the
        # non-reportable marker so the activity interceptor doesn't send it to error tracking.
        assert isinstance(exc_info.value, NonReportableError) == (expected_type == "validation_error")
        recalc.refresh_from_db()
        assert "m1" in recalc.metric_errors
        row = ExperimentMetricResult.objects.get(experiment=exp, metric_uuid="m1")
        assert row.status == ExperimentMetricResult.Status.FAILED

    @parameterized.expand([("auto", None), ("direct", PrecomputationMode.DIRECT)])
    def test_run_window_and_precompute_mode_reach_the_runner(self, _name: str, mode: PrecomputationMode | None):
        # The run's shared query_to MUST be threaded into the ClickHouse query bounds via the runner's
        # as_of, not just stored on the result row. Without as_of the runner falls back to its own now(),
        # so every metric in the run queries a slightly different time window — silently violating the
        # "one query_to for the whole run" guarantee. Stored value would look correct; actual query bounds
        # would not. Reference: workflow #3's backfill activity does the same thing.
        exp = self._experiment(flag_key="calc-as-of", metrics=[test_helpers._mean_metric("m1")])
        recalc = self._recalc(exp, metric_uuids=["m1"])

        with test_helpers._patched_runner() as mock_runner:
            mock_runner.return_value.run.return_value.model_dump.return_value = {}
            test_helpers._calculate(exp.id, "m1", str(recalc.id), test_helpers._QUERY_TO, precomputation_mode=mode)

        mock_runner.assert_called_once()
        kwargs = mock_runner.call_args.kwargs
        assert kwargs["as_of"] == datetime.fromisoformat(test_helpers._QUERY_TO)
        assert kwargs["workload"] == Workload.OFFLINE
        assert kwargs["query"].precomputation_mode == mode

    def test_query_from_matches_experiment_start_date_on_result_row(self):
        # Companion to test_query_to_is_passed_as_as_of_to_runner: the lower bound of the run's
        # time window is experiment.start_date, threaded into the runner via the experiment object it
        # constructs and stored on the result row by the result store's run write (query_from=experiment.start_date).
        # This test pins the stored-row side. If the runner ever changes how it derives query_from, or if a
        # future refactor decouples the stored value from what the runner actually queries, the same class
        # of silent-miscalculation bug we just fixed for query_to could reappear here.
        exp = self._experiment(flag_key="calc-query-from", metrics=[test_helpers._mean_metric("m1")])
        recalc = self._recalc(exp, metric_uuids=["m1"])

        with test_helpers._patched_runner() as mock_runner:
            mock_runner.return_value.run.return_value.model_dump.return_value = {}
            test_helpers._calculate(exp.id, "m1", str(recalc.id), test_helpers._QUERY_TO)

        # Runner gets the experiment whose start_date is the source of truth for the lower bound.
        mock_runner.assert_called_once()
        assert mock_runner.call_args.kwargs["team"] == exp.team
        # And the persisted row's query_from matches that same start_date — so reader and writer agree.
        row = ExperimentMetricResult.objects.get(experiment=exp, metric_uuid="m1")
        assert row.query_from == exp.start_date

    def test_query_id_is_persisted_on_result_row(self):
        # The deterministic client_query_id is stamped into ClickHouse's query_id and stored on the row so a
        # metric's executions are greppable in system.query_log by the `{team}_{client_query_id}_` prefix.
        exp = self._experiment(flag_key="calc-query-id", metrics=[test_helpers._mean_metric("m1")])
        recalc = self._recalc(exp, metric_uuids=["m1"])

        with test_helpers._patched_runner() as mock_runner:
            mock_runner.return_value.run.return_value.model_dump.return_value = {}
            test_helpers._calculate(exp.id, "m1", str(recalc.id), test_helpers._QUERY_TO)

        row = ExperimentMetricResult.objects.get(experiment=exp, metric_uuid="m1")
        assert row.query_id == f"experiment_metric_recalc_{recalc.id}_m1_attempt01"

    @parameterized.expand(
        [
            ("activity_queue", "activity-q", "activity-q", ClickHouseUser.EXPERIMENTS),
            ("precompute_queue", "activity-q", "precompute-q", ClickHouseUser.EXPERIMENTS),
            ("build_queue", "activity-q", "build-q", ClickHouseUser.EXPERIMENTS),
            ("direct_heavy_queue", "activity-q", "direct-heavy-q", ClickHouseUser.EXPERIMENTS),
            ("main_queue", "activity-q", "main-q", ClickHouseUser.CACHE_WARMUP),
            ("collapsed_queues", "main-q", "main-q", ClickHouseUser.CACHE_WARMUP),
        ]
    )
    def test_queries_run_as_the_clickhouse_user_of_their_task_queue(
        self, name: str, activity_task_queue: str, task_queue: str, expected_user: ClickHouseUser
    ):
        exp = self._experiment(flag_key=f"calc-ch-user-{name}", metrics=[test_helpers._mean_metric("m1")])
        recalc = self._recalc(exp, metric_uuids=["m1"])

        def run_metric_and_precompute_queries(**kwargs):
            sync_execute("SELECT 1", flush=False)
            # The precompute insert runs inside its own tags_context, as run_lazy_computation_insert does.
            with tags_context(client_query_id="precompute-job"):
                sync_execute("SELECT 2", flush=False)
            return MagicMock(model_dump=MagicMock(return_value={}))

        with (
            override_settings(
                EXPERIMENTS_RECALCULATION_TASK_QUEUE="main-q",
                EXPERIMENTS_RECALCULATION_ACTIVITY_TASK_QUEUE=activity_task_queue,
                EXPERIMENTS_RECALCULATION_PRECOMPUTE_TASK_QUEUE="precompute-q",
                EXPERIMENTS_RECALCULATION_BUILD_TASK_QUEUE="build-q",
                EXPERIMENTS_RECALCULATION_DIRECT_HEAVY_TASK_QUEUE="direct-heavy-q",
            ),
            patch("posthog.clickhouse.client.execute.get_client_from_pool") as client_from_pool,
            test_helpers._patched_runner() as mock_runner,
        ):
            client_from_pool.return_value.__enter__.return_value.execute.return_value = []
            mock_runner.return_value.run.side_effect = run_metric_and_precompute_queries
            test_helpers._calculate(exp.id, "m1", str(recalc.id), test_helpers._QUERY_TO, task_queue=task_queue)

        assert [call.args[3] for call in client_from_pool.call_args_list] == [expected_user, expected_user]

    def test_multiple_failures_accumulate_in_metric_errors(self):
        # Two metrics fail in sequence (not in parallel — that would need threads + a real Postgres). Pins the
        # merge-into-dict behavior: each failure writes its own entry keyed by metric_uuid, no overwriting.
        # The select_for_update guard against concurrent writers is exercised by the production code, not here.
        exp = self._experiment(flag_key="calc-accumulate", metrics=[])
        recalc = self._recalc(exp, metric_uuids=["missing-a", "missing-b"])

        test_helpers._calculate(exp.id, "missing-a", str(recalc.id), test_helpers._QUERY_TO)
        test_helpers._calculate(exp.id, "missing-b", str(recalc.id), test_helpers._QUERY_TO)

        recalc.refresh_from_db()
        assert len(recalc.metric_errors) == 2
        assert set(recalc.metric_errors.keys()) == {"missing-a", "missing-b"}

    def test_skips_query_when_completed_result_already_exists_for_this_fingerprint(self):
        # Speed optimization: if a COMPLETED row already exists at this (experiment, metric_uuid, query_to)
        # under THIS run's recalc fingerprint, the metric is unchanged and already computed for this window, so
        # the activity returns success without re-running the ClickHouse query. The fingerprint is the
        # correctness gate: a config change produces a different fingerprint, so no match, and it recomputes.
        metric = test_helpers._mean_metric("m1")
        exp = self._experiment(flag_key="calc-skip-existing", metrics=[metric])
        query_to = datetime.fromisoformat(test_helpers._QUERY_TO)
        recalc_fp = _recalc_fingerprint(_calculation_key(exp, "m1"))
        existing = ExperimentMetricResult.objects.create(
            experiment=exp,
            metric_uuid="m1",
            fingerprint=recalc_fp,
            query_from=query_to,
            query_to=query_to,
            status=ExperimentMetricResult.Status.COMPLETED,
            result={"already": "computed"},
        )
        recalc = self._recalc(exp, metric_uuids=["m1"])
        # A crash between a prior attempt's result write and retry cleanup lands on this path; the skip
        # must still clear the entry so a completed metric can't keep reporting as retrying.
        recalc.metric_retries = {"m1": {"attempt": 3, "max_attempts": 8}}
        recalc.save(update_fields=["metric_retries"])

        with test_helpers._patched_runner() as mock_runner:
            result = test_helpers._calculate(exp.id, "m1", str(recalc.id), test_helpers._QUERY_TO)

        mock_runner.assert_not_called()
        assert result.success is True
        recalc.refresh_from_db()
        assert recalc.metric_retries == {}
        # The existing row is left untouched: same id, same result.
        rows = ExperimentMetricResult.objects.filter(experiment=exp, metric_uuid="m1", query_to=query_to)
        assert rows.count() == 1
        row = rows.get()
        assert row.id == existing.id
        assert row.result == {"already": "computed"}

    @parameterized.expand(
        [
            ("a_result_replaces_it", None, "version_2", {"fresh": True}, "current", (1, 0)),
            ("a_failure_keeps_it", StatisticError("Not enough data"), "version_1", {"saved": True}, "unknown", (0, 1)),
        ]
    )
    def test_recomputes_a_result_under_another_key_version(
        self,
        _name: str,
        error: Exception | None,
        expected_key: str,
        expected_result: dict,
        expected_configuration: str,
        expected_counters: tuple[int, int],
    ) -> None:
        self.enterContext(patch_calculation_key_version(2))
        exp = self._experiment(flag_key=f"calc-other-version-{_name}", metrics=[test_helpers._mean_metric("m1")])
        query_to = datetime.fromisoformat(test_helpers._QUERY_TO)
        calculation_config = get_metric_calculation_config(exp, "m1")
        assert calculation_config is not None
        keys = {
            "version_1": _recalc_fingerprint(calculation_config.key_for_version(1)),
            "version_2": _recalc_fingerprint(calculation_config.key_for_version(2)),
        }
        ExperimentMetricResult.objects.create(
            experiment=exp,
            metric_uuid="m1",
            fingerprint=keys["version_1"],
            query_from=query_to,
            query_to=query_to,
            status=ExperimentMetricResult.Status.COMPLETED,
            result={"saved": True},
        )
        recalc = self._recalc(exp, metric_uuids=["m1"])

        with test_helpers._patched_runner() as mock_runner:
            if error is None:
                mock_runner.return_value.run.return_value.model_dump.return_value = {"fresh": True}
            else:
                mock_runner.return_value.run.side_effect = error
            test_helpers._calculate(exp.id, "m1", str(recalc.id), test_helpers._QUERY_TO, calculation_key_version=2)

        mock_runner.assert_called_once()
        recalc.refresh_from_db()
        assert {uuid: entry["calculation_key"] for uuid, entry in recalc.metric_errors.items()} == (
            {} if error is None else {"m1": calculation_config.key_for_version(2)}
        )
        results = get_run_results(recalc)
        assert [(r["status"], r["result"], r["configuration_status"]) for r in results] == [
            (ExperimentMetricResult.Status.COMPLETED, expected_result, expected_configuration)
        ]
        row = ExperimentMetricResult.objects.get(experiment=exp, metric_uuid="m1", query_to=query_to)
        assert row.fingerprint == keys[expected_key]
        payload = build_job_payload(recalc)
        assert (payload["completed_metrics"], payload["failed_metrics"]) == expected_counters

    def test_excluded_variants_change_recomputes(self):
        # A cached row computed before a variant was excluded must not satisfy the skip check: the exclusion
        # set feeds the fingerprint, so the stale row's fingerprint no longer matches and the query re-runs.
        metric = test_helpers._mean_metric("m1")
        exp = self._experiment(flag_key="calc-excluded", metrics=[metric])
        query_to = datetime.fromisoformat(test_helpers._QUERY_TO)
        recalc_fp = _recalc_fingerprint(_calculation_key(exp, "m1"))
        ExperimentMetricResult.objects.create(
            experiment=exp,
            metric_uuid="m1",
            fingerprint=recalc_fp,
            query_from=query_to,
            query_to=query_to,
            status=ExperimentMetricResult.Status.COMPLETED,
            result={"stale": True},
        )
        exp.excluded_variants = ["test"]
        exp.save(update_fields=["excluded_variants"])
        recalc = self._recalc(exp, metric_uuids=["m1"])

        with test_helpers._patched_runner() as mock_runner:
            mock_runner.return_value.run.return_value.model_dump.return_value = {}
            test_helpers._calculate(exp.id, "m1", str(recalc.id), test_helpers._QUERY_TO)

        mock_runner.assert_called_once()

    @parameterized.expand([("key_version_1", 1), ("key_version_2", 2)])
    def test_a_settings_change_before_the_runner_reads_them_is_not_stored_under_the_earlier_key(
        self, _name: str, key_version: int
    ) -> None:
        metric = test_helpers._mean_metric("m1")
        exp = self._experiment(flag_key="calc-settings-race", metrics=[metric])
        recalc = self._recalc(exp, metric_uuids=["m1"])
        team_config = get_or_create_team_extension(self.team, TeamExperimentsConfig)
        runners: list[ExperimentQueryRunner] = []

        def change_settings_then_build_runner(*args, **kwargs) -> ExperimentQueryRunner:
            # Version 1 hashes the stats method, and version 2 also hashes the CUPED team default.
            Experiment.objects.filter(id=exp.id).update(stats_config={"method": "frequentist"})
            team_config.default_cuped_enabled = not team_config.default_cuped_enabled
            team_config.save()
            runner = ExperimentQueryRunner(*args, **kwargs)
            runners.append(runner)
            return runner

        computed = MagicMock()
        computed.model_dump.return_value = {"variant_results": []}
        with (
            patch(
                "products.experiments.backend.temporal.recalculation.calculation.ExperimentQueryRunner",
                side_effect=change_settings_then_build_runner,
            ),
            patch.object(ExperimentQueryRunner, "run", return_value=computed),
        ):
            test_helpers._calculate(
                exp.id, "m1", str(recalc.id), test_helpers._QUERY_TO, calculation_key_version=key_version
            )

        [runner] = runners
        executed_key = runner.calculation_config.settings.build_metric_config(
            metric_id="m1", role="primary", definition=metric
        ).key_for_version(key_version)
        stored = ExperimentMetricResult.objects.filter(experiment=exp, metric_uuid="m1").values_list(
            "fingerprint", flat=True
        )
        assert list(stored) == [_recalc_fingerprint(executed_key)]

    @parameterized.expand(
        [
            # (name, metric_uuid, metrics_on_experiment, run_with_mocked_failure, expected_result_rows)
            # Discovery-step failure: m1 in the recalc's discovered set but absent from the experiment (deleted
            # between discovery and calc). No result row written, only metric_errors.
            ("discovery_failure", "m1", [], False, 0),
            # Calculation-step failure: m1 resolves, runner raises, writes both metric_errors and exactly one
            # FAILED result row (update_or_create overwrites on retry rather than inserting).
            ("calculation_failure", "m1", [test_helpers._mean_metric("m1")], True, 1),
        ]
    )
    def test_retry_does_not_double_count(
        self, name: str, metric_uuid: str, metrics: list, mock_runner_failure: bool, expected_result_rows: int
    ):
        # Temporal retries the whole activity on transient failure. The run write is idempotent (update_or_create
        # keyed on experiment, metric_uuid and query_to) and metric_errors is keyed by metric_uuid, so a second run
        # must leave state identical to the first — no inflated counts, no duplicate result rows.
        exp = self._experiment(flag_key=f"retry-{name}", metrics=metrics)
        recalc = self._recalc(exp, metric_uuids=[metric_uuid])

        def _run() -> None:
            if mock_runner_failure:
                with test_helpers._patched_runner() as mock_runner:
                    mock_runner.return_value.run.side_effect = RuntimeError("kaboom")
                    # Calc-step failures now re-raise so Temporal can retry transient errors. The record is
                    # written before the re-raise, so the assertions below still hold across attempts.
                    with pytest.raises(RuntimeError, match="kaboom"):
                        test_helpers._calculate(exp.id, metric_uuid, str(recalc.id), test_helpers._QUERY_TO)
            else:
                test_helpers._calculate(exp.id, metric_uuid, str(recalc.id), test_helpers._QUERY_TO)

        _run()
        _run()  # simulated Temporal retry

        recalc.refresh_from_db()
        assert len(recalc.metric_errors) == 1
        assert metric_uuid in recalc.metric_errors
        # Exact count per case: 0 for discovery failures (no result write), 1 for calc failures
        # (one FAILED row, overwritten on retry rather than duplicated).
        assert (
            ExperimentMetricResult.objects.filter(experiment=exp, metric_uuid=metric_uuid).count()
            == expected_result_rows
        )

    @parameterized.expand(
        [
            # (name, build_kwargs, expected_error_fragment)
            # The workflow constructs all four args from its own state, so any mismatch here means a workflow
            # bug. The activity must fail non-retryable (no point in retrying a deterministic failure).
            (
                "experiment_id_mismatch",
                {"experiment_id_offset": 9999},
                "does not match recalc.experiment_id",
            ),
            (
                "metric_uuid_not_in_set",
                {"metric_uuid_override": "not-in-recalc-set"},
                "is not in recalc",
            ),
            (
                "query_to_mismatch",
                {"query_to_override": "2030-01-01T00:00:00+00:00"},
                "does not match recalc.query_to",
            ),
            (
                "query_to_unset_on_recalc",
                {"clear_query_to": True},
                "has no query_to set",
            ),
            # Parse failure before the cross-checks even run — without explicit handling this would escape as a
            # bare ValueError, hit Temporal's broad retry policy, and burn slots on a deterministic parse error.
            (
                "query_to_unparseable",
                {"query_to_override": "not-an-iso-string"},
                "is not a valid ISO datetime string",
            ),
        ]
    )
    def test_input_validation_fails_non_retryable(self, name: str, build_kwargs: dict, expected_fragment: str):
        exp = self._experiment(flag_key=f"validation-{name}", metrics=[test_helpers._mean_metric("m1")])
        recalc = self._recalc(exp, metric_uuids=["m1"])
        if build_kwargs.get("clear_query_to"):
            recalc.query_to = None
            recalc.save(update_fields=["query_to"])

        call_experiment_id = exp.id + build_kwargs.get("experiment_id_offset", 0)
        call_metric_uuid = build_kwargs.get("metric_uuid_override", "m1")
        call_query_to = build_kwargs.get("query_to_override", test_helpers._QUERY_TO)

        with pytest.raises(ApplicationError) as exc_info:
            test_helpers._calculate(call_experiment_id, call_metric_uuid, str(recalc.id), call_query_to)

        assert expected_fragment in str(exc_info.value)
        assert exc_info.value.non_retryable is True

    def test_unexpected_error_calls_capture_exception_and_caps_message(self):
        # Unexpected exceptions get captured to Sentry and re-raised for Temporal retry. The stored result row
        # carries the capped error message so the UI sees what happened even though the activity re-raised.
        exp = self._experiment(flag_key="calc-capture", metrics=[test_helpers._mean_metric("m1")])
        recalc = self._recalc(exp, metric_uuids=["m1"])

        with (
            test_helpers._patched_runner() as mock_runner,
            patch("products.experiments.backend.temporal.recalculation.calculation.capture_exception") as mock_capture,
        ):
            mock_runner.return_value.run.side_effect = RuntimeError("x" * 5000)
            with pytest.raises(RuntimeError):
                test_helpers._calculate(exp.id, "m1", str(recalc.id), test_helpers._QUERY_TO)

        assert mock_capture.called
        row = ExperimentMetricResult.objects.get(experiment=exp, metric_uuid="m1")
        assert row.status == ExperimentMetricResult.Status.FAILED
        assert row.error_message is not None
        assert len(row.error_message) <= 2000

    def test_cancel_metric_query_tags_its_queries(self):
        # The kill runs in its own thread, so it inherits none of the calc body's tags. Untagged sync_execute
        # calls raise in local dev, which makes the kill fail silently there.
        exp = self._experiment(flag_key="cancel-tags", metrics=[test_helpers._mean_metric("m1")])
        recalc = self._recalc(exp, metric_uuids=["m1"])
        seen: dict = {}

        def _capture(team_id: int, client_query_id: str) -> None:
            seen["args"] = (team_id, client_query_id)
            seen["tags"] = get_query_tags().model_copy()

        with (
            patch("products.experiments.backend.temporal.recalculation.calculation.close_old_connections"),
            patch("products.experiments.backend.temporal.recalculation.calculation.cancel_query_on_cluster", _capture),
        ):
            _cancel_raw(str(recalc.id), "m1", 3)

        assert seen["args"] == (self.team.id, f"experiment_metric_recalc_{recalc.id}_m1_attempt03")
        assert (seen["tags"].team_id, seen["tags"].product, seen["tags"].feature) == (
            self.team.id,
            Product.EXPERIMENTS,
            Feature.CACHE_WARMUP,
        )
