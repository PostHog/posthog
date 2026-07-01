from contextlib import contextmanager
from datetime import datetime, timedelta

import pytest
from freezegun import freeze_time
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from clickhouse_driver.errors import ServerException
from parameterized import parameterized
from temporalio.exceptions import ApplicationError

from posthog.exceptions import ClickHouseQueryMemoryLimitExceeded, ClickHouseQueryTimeOut

from products.experiments.backend.hogql_queries.experiment_metric_fingerprint import compute_metric_fingerprint
from products.experiments.backend.hogql_queries.utils import get_experiment_stats_method
from products.experiments.backend.models.experiment import (
    Experiment,
    ExperimentMetricResult,
    ExperimentMetricsRecalculation,
    ExperimentSavedMetric,
    ExperimentToSavedMetric,
)
from products.experiments.backend.temporal.models import RecalculationProgressUpdate
from products.experiments.backend.temporal.recalc_fingerprint import compute_recalc_fingerprint
from products.experiments.backend.temporal.recalculation_logic import (
    _calculate_experiment_metric_for_recalculation_sync,
    _discover_experiment_metrics_sync,
    _store_result,
    _update_recalculation_progress_sync,
)
from products.experiments.stats.shared.statistics import StatisticError
from products.feature_flags.backend.models.feature_flag import FeatureFlag

_discover_raw = _discover_experiment_metrics_sync.func  # type: ignore[attr-defined]
_update_raw = _update_recalculation_progress_sync.func  # type: ignore[attr-defined]
_calculate_raw = _calculate_experiment_metric_for_recalculation_sync.func  # type: ignore[attr-defined]


def _discover(recalculation_id: str):
    with patch("products.experiments.backend.temporal.recalculation_logic.close_old_connections"):
        return _discover_raw(recalculation_id)


def _update(update: RecalculationProgressUpdate):
    with patch("products.experiments.backend.temporal.recalculation_logic.close_old_connections"):
        return _update_raw(update)


def _calculate(
    experiment_id: int,
    metric_uuid: str,
    recalculation_id: str,
    query_to: str,
    metric_type: str = "primary",
    is_final_attempt: bool = True,
):
    with patch("products.experiments.backend.temporal.recalculation_logic.close_old_connections"):
        return _calculate_raw(experiment_id, metric_uuid, recalculation_id, query_to, metric_type, is_final_attempt)


@pytest.mark.django_db(transaction=True)
class TestRecalculationActivities(BaseTest):
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

    def _experiment(self, flag_key: str) -> Experiment:
        return Experiment.objects.create(
            team=self.team, created_by=self.user, feature_flag=self._flag(flag_key), name="exp"
        )

    def _recalc(self, exp: Experiment) -> ExperimentMetricsRecalculation:
        return ExperimentMetricsRecalculation.objects.create(team=self.team, experiment=exp)

    def _attach_saved_metric(self, exp: Experiment, uuid: str, metric_type: str) -> None:
        saved = ExperimentSavedMetric.objects.create(
            team=self.team,
            name=f"saved-{uuid}",
            query={"uuid": uuid, "kind": "ExperimentMetric", "metric_type": "mean"},
        )
        ExperimentToSavedMetric.objects.create(experiment=exp, saved_metric=saved, metadata={"type": metric_type})

    @parameterized.expand(
        [
            (
                "primary_and_secondary",
                [{"uuid": "m1", "metric_type": "mean", "kind": "ExperimentMetric"}],
                [{"uuid": "m2", "metric_type": "mean", "kind": "ExperimentMetric"}],
                [],
                {"m1", "m2"},
                {"primary", "secondary"},
            ),
            ("no_metrics", [], [], [], set(), set()),
            (
                "primary_only",
                [{"uuid": "m1", "metric_type": "mean", "kind": "ExperimentMetric"}],
                [],
                [],
                {"m1"},
                {"primary"},
            ),
            (
                "saved_metrics_only",
                [],
                [],
                [("s1", "primary"), ("s2", "secondary")],
                {"s1", "s2"},
                {"primary", "secondary"},
            ),
            (
                "inline_and_saved_mixed",
                [{"uuid": "m1", "metric_type": "mean", "kind": "ExperimentMetric"}],
                [],
                [("s1", "secondary")],
                {"m1", "s1"},
                {"primary", "secondary"},
            ),
        ]
    )
    def test_discover_persists_metric_uuids(self, name: str, primary, secondary, saved, expected_uuids, expected_types):
        exp = self._experiment(flag_key=f"discover-{name}")
        exp.metrics = primary
        exp.metrics_secondary = secondary
        exp.save()
        for uuid, metric_type in saved:
            self._attach_saved_metric(exp, uuid, metric_type)
        recalc = self._recalc(exp)

        metrics = _discover(str(recalc.id))

        recalc.refresh_from_db()
        assert set(recalc.metric_uuids) == expected_uuids
        assert {m.metric_uuid for m in metrics} == expected_uuids
        assert {m.metric_type for m in metrics} == expected_types

    @parameterized.expand(
        [
            (
                "start",
                {
                    "status": "in_progress",
                    "total_metrics": 3,
                    "metric_uuids": ["m1", "m2", "m3"],
                    "mark_started": True,
                },
                "in_progress",
                True,  # expects query_to set + returned
            ),
            (
                "finish",
                {"status": "completed", "mark_completed": True},
                "completed",
                False,  # finish does not set/return query_to
            ),
        ]
    )
    def test_update_progress(self, name: str, update_kwargs: dict, expected_status: str, expects_query_to: bool):
        recalc = self._recalc(self._experiment(flag_key=f"progress-{name}"))
        returned = _update(RecalculationProgressUpdate(recalculation_id=str(recalc.id), **update_kwargs))

        recalc.refresh_from_db()
        assert recalc.status == expected_status

        if expects_query_to:
            assert recalc.started_at is not None
            assert recalc.total_metrics == update_kwargs["total_metrics"]
            assert recalc.metric_uuids == update_kwargs["metric_uuids"]
            assert recalc.query_to is not None
            # Returns the query_to it set (ISO string) so the workflow can thread it into calc activities.
            assert returned == recalc.query_to.isoformat()
        else:
            assert recalc.completed_at is not None
            assert returned is None

    def test_mark_started_is_first_write_wins_on_retry(self):
        # Temporal retries the start activity (network blip, worker crash) — the second attempt must NOT move
        # query_to/started_at forward. If it did, any calc activity already in flight from the first attempt
        # would persist ExperimentMetricResult rows with the old query_to, while the recalc row points at the
        # new one — orphaning those rows from the API's perspective.
        recalc = self._recalc(self._experiment(flag_key="progress-retry-start"))

        def _start() -> str | None:
            return _update(
                RecalculationProgressUpdate(
                    recalculation_id=str(recalc.id),
                    status="in_progress",
                    total_metrics=3,
                    metric_uuids=["m1", "m2", "m3"],
                    mark_started=True,
                )
            )

        first = _start()
        recalc.refresh_from_db()
        first_query_to = recalc.query_to
        first_started_at = recalc.started_at
        assert first_query_to is not None  # mark_started=True populates it

        second = _start()
        recalc.refresh_from_db()

        # DB state unchanged after retry — the conditional UPDATE matched zero rows.
        assert recalc.query_to == first_query_to
        assert recalc.started_at == first_started_at
        # Both attempts return the same canonical query_to so the workflow threads the same value either way.
        assert first == second == first_query_to.isoformat()

    @parameterized.expand(
        [
            # name, end_date_offset_days (None = running experiment), expect query_to == end_date
            ("running_uses_now", None, False),
            ("stopped_uses_end_date", -5, True),
            ("future_end_uses_now", 5, False),
        ]
    )
    @freeze_time("2026-06-23T05:00:00Z")
    def test_mark_started_query_to_is_data_window_end(self, name: str, end_date_offset_days, expect_end_date: bool):
        # query_to is the data-window end (experiment_window_end), not bare now. For a stopped experiment it
        # resolves to end_date — a fixed value — so reruns reuse the same result row instead of appending a
        # redundant post-end timeseries point. Running / future-dated experiments still advance with now.
        now = timezone.now()
        exp = self._experiment(flag_key=f"window-end-{name}")
        if end_date_offset_days is not None:
            exp.end_date = now + timedelta(days=end_date_offset_days)
            exp.save(update_fields=["end_date"])
        recalc = self._recalc(exp)

        _update(
            RecalculationProgressUpdate(
                recalculation_id=str(recalc.id),
                status="in_progress",
                total_metrics=1,
                metric_uuids=["m1"],
                mark_started=True,
            )
        )

        recalc.refresh_from_db()
        assert recalc.query_to is not None
        if expect_end_date:
            assert recalc.query_to == now + timedelta(days=end_date_offset_days)
        else:
            assert recalc.query_to == now

    def test_mark_completed_is_first_write_wins_on_retry(self):
        # Symmetric to mark_started: a retried finish activity must not re-stamp completed_at.
        recalc = self._recalc(self._experiment(flag_key="progress-retry-finish"))

        def _finish() -> str | None:
            return _update(
                RecalculationProgressUpdate(
                    recalculation_id=str(recalc.id),
                    status="completed",
                    mark_completed=True,
                )
            )

        _finish()
        recalc.refresh_from_db()
        first_completed_at = recalc.completed_at
        first_status = recalc.status

        _finish()
        recalc.refresh_from_db()

        assert recalc.completed_at == first_completed_at
        assert recalc.status == first_status

    @parameterized.expand(
        [
            # Contract: exactly one of mark_started / mark_completed must be true. Both-true or neither-true
            # is a workflow bug — fail non-retryable so Temporal terminates promptly.
            ("both_true", {"mark_started": True, "mark_completed": True}),
            ("neither", {}),
        ]
    )
    def test_progress_update_requires_exactly_one_lifecycle_flag(self, name: str, flags: dict):
        recalc = self._recalc(self._experiment(flag_key=f"progress-mutex-{name}"))

        with pytest.raises(ApplicationError) as exc_info:
            _update(RecalculationProgressUpdate(recalculation_id=str(recalc.id), **flags))

        assert "exactly one of mark_started or mark_completed" in str(exc_info.value)
        assert exc_info.value.non_retryable is True


_QUERY_TO = "2026-05-29T12:00:00+00:00"


def _mean_metric(uuid: str) -> dict:
    # ExperimentMeanMetric requires a `source`; a bare {uuid, metric_type} dict fails pydantic validation.
    return {
        "uuid": uuid,
        "kind": "ExperimentMetric",
        "metric_type": "mean",
        "source": {"kind": "EventsNode", "event": "purchase"},
    }


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
            query_to=datetime.fromisoformat(_QUERY_TO),
        )

    def test_metric_disappeared_between_discovery_and_calc(self):
        # Discovery included m1 in the recalc's metric set (so input validation passes), but the experiment
        # was edited and m1 is no longer present — the calc activity's inner lookup must surface this as a
        # discovery-step failure rather than crashing.
        exp = self._experiment(flag_key="calc-missing", metrics=[])
        recalc = self._recalc(exp, metric_uuids=["m1"])

        result = _calculate(exp.id, "m1", str(recalc.id), _QUERY_TO)

        assert result.success is False
        assert result.error_step == "discovery"
        recalc.refresh_from_db()
        assert len(recalc.metric_errors) == 1
        assert "m1" in recalc.metric_errors

    def test_bad_metric_type_fails_at_calculation(self):
        # Legacy metrics never reach this workflow, so there's no discovery-time type guard; an unexpected
        # metric_type raises while building the metric. The activity records the failure to metric_errors
        # and re-raises so Temporal's retry policy can handle potentially transient errors.
        exp = self._experiment(
            flag_key="calc-badtype",
            metrics=[{"uuid": "m-bad", "metric_type": "nonsense", "kind": "ExperimentMetric"}],
        )
        recalc = self._recalc(exp, metric_uuids=["m-bad"])

        with pytest.raises(KeyError):
            _calculate(exp.id, "m-bad", str(recalc.id), _QUERY_TO)

        recalc.refresh_from_db()
        assert len(recalc.metric_errors) == 1
        assert "m-bad" in recalc.metric_errors

    def test_missing_start_date_fails(self):
        exp = self._experiment(flag_key="calc-no-start", with_start_date=False, metrics=[_mean_metric("m1")])
        recalc = self._recalc(exp, metric_uuids=["m1"])

        result = _calculate(exp.id, "m1", str(recalc.id), _QUERY_TO)

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
            query=_mean_metric("s1"),
        )
        ExperimentToSavedMetric.objects.create(experiment=exp, saved_metric=saved, metadata={"type": "primary"})
        recalc = self._recalc(exp, metric_uuids=["s1"])

        with patch("products.experiments.backend.temporal.recalculation_logic.ExperimentQueryRunner") as mock_runner:
            mock_runner.return_value.run.side_effect = RuntimeError("kaboom")
            with pytest.raises(RuntimeError, match="kaboom"):
                _calculate(exp.id, "s1", str(recalc.id), _QUERY_TO)

        # Found the saved metric (did not fail at discovery), failure was recorded before re-raise.
        recalc.refresh_from_db()
        assert "s1" in recalc.metric_errors

    def test_transient_failure_is_not_persisted_until_the_final_attempt(self):
        # A retryable (transient) failure on a non-final attempt re-raises for Temporal to retry but must NOT
        # persist a FAILED row or a metric_errors entry, so the frontend keeps the metric loading instead of
        # flashing an error for a failure that may still succeed. The final attempt persists it.
        exp = self._experiment(flag_key="calc-transient", metrics=[_mean_metric("m1")])
        recalc = self._recalc(exp, metric_uuids=["m1"])

        with patch("products.experiments.backend.temporal.recalculation_logic.ExperimentQueryRunner") as mock_runner:
            mock_runner.return_value.run.side_effect = RuntimeError("transient blip")

            # Non-final attempt: re-raises, but nothing is recorded.
            with pytest.raises(RuntimeError, match="transient blip"):
                _calculate(exp.id, "m1", str(recalc.id), _QUERY_TO, is_final_attempt=False)
            recalc.refresh_from_db()
            assert recalc.metric_errors == {}
            assert not ExperimentMetricResult.objects.filter(experiment=exp, metric_uuid="m1").exists()

            # Final attempt: now the failure is persisted for the UI.
            with pytest.raises(RuntimeError, match="transient blip"):
                _calculate(exp.id, "m1", str(recalc.id), _QUERY_TO, is_final_attempt=True)
            recalc.refresh_from_db()
            assert "m1" in recalc.metric_errors

    def test_query_to_is_passed_as_as_of_to_runner(self):
        # The run's shared query_to MUST be threaded into the ClickHouse query bounds via the runner's
        # as_of, not just stored on the result row. Without as_of the runner falls back to its own now(),
        # so every metric in the run queries a slightly different time window — silently violating the
        # "one query_to for the whole run" guarantee. Stored value would look correct; actual query bounds
        # would not. Reference: workflow #3's backfill activity does the same thing.
        exp = self._experiment(flag_key="calc-as-of", metrics=[_mean_metric("m1")])
        recalc = self._recalc(exp, metric_uuids=["m1"])

        with patch("products.experiments.backend.temporal.recalculation_logic.ExperimentQueryRunner") as mock_runner:
            mock_runner.return_value.run.return_value.model_dump.return_value = {}
            _calculate(exp.id, "m1", str(recalc.id), _QUERY_TO)

        mock_runner.assert_called_once()
        kwargs = mock_runner.call_args.kwargs
        assert kwargs["as_of"] == datetime.fromisoformat(_QUERY_TO)

    def test_query_from_matches_experiment_start_date_on_result_row(self):
        # Companion to test_query_to_is_passed_as_as_of_to_runner: the lower bound of the run's
        # time window is experiment.start_date, threaded into the runner via the experiment object it
        # constructs and stored on the result row via _store_result(query_from=experiment.start_date).
        # This test pins the stored-row side. If the runner ever changes how it derives query_from, or if a
        # future refactor decouples the stored value from what the runner actually queries, the same class
        # of silent-miscalculation bug we just fixed for query_to could reappear here.
        exp = self._experiment(flag_key="calc-query-from", metrics=[_mean_metric("m1")])
        recalc = self._recalc(exp, metric_uuids=["m1"])

        with patch("products.experiments.backend.temporal.recalculation_logic.ExperimentQueryRunner") as mock_runner:
            mock_runner.return_value.run.return_value.model_dump.return_value = {}
            _calculate(exp.id, "m1", str(recalc.id), _QUERY_TO)

        # Runner gets the experiment whose start_date is the source of truth for the lower bound.
        mock_runner.assert_called_once()
        assert mock_runner.call_args.kwargs["team"] == exp.team
        # And the persisted row's query_from matches that same start_date — so reader and writer agree.
        row = ExperimentMetricResult.objects.get(experiment=exp, metric_uuid="m1")
        assert row.query_from == exp.start_date

    def test_query_id_is_persisted_on_result_row(self):
        # The deterministic client_query_id is stamped into ClickHouse's query_id and stored on the row so a
        # metric's executions are greppable in system.query_log by the `{team}_{client_query_id}_` prefix.
        exp = self._experiment(flag_key="calc-query-id", metrics=[_mean_metric("m1")])
        recalc = self._recalc(exp, metric_uuids=["m1"])

        with patch("products.experiments.backend.temporal.recalculation_logic.ExperimentQueryRunner") as mock_runner:
            mock_runner.return_value.run.return_value.model_dump.return_value = {}
            _calculate(exp.id, "m1", str(recalc.id), _QUERY_TO)

        row = ExperimentMetricResult.objects.get(experiment=exp, metric_uuid="m1")
        assert row.query_id == f"experiment_metric_recalc_{recalc.id}_m1"

    def test_multiple_failures_accumulate_in_metric_errors(self):
        # Two metrics fail in sequence (not in parallel — that would need threads + a real Postgres). Pins the
        # merge-into-dict behavior: each failure writes its own entry keyed by metric_uuid, no overwriting.
        # The select_for_update guard against concurrent writers is exercised by the production code, not here.
        exp = self._experiment(flag_key="calc-accumulate", metrics=[])
        recalc = self._recalc(exp, metric_uuids=["missing-a", "missing-b"])

        _calculate(exp.id, "missing-a", str(recalc.id), _QUERY_TO)
        _calculate(exp.id, "missing-b", str(recalc.id), _QUERY_TO)

        recalc.refresh_from_db()
        assert len(recalc.metric_errors) == 2
        assert set(recalc.metric_errors.keys()) == {"missing-a", "missing-b"}

    def test_skips_query_when_completed_result_already_exists_for_this_fingerprint(self):
        # Speed optimization: if a COMPLETED row already exists at this (experiment, metric_uuid, query_to)
        # under THIS run's recalc fingerprint, the metric is unchanged and already computed for this window, so
        # the activity returns success without re-running the ClickHouse query. The fingerprint is the
        # correctness gate: a config change produces a different fingerprint, so no match, and it recomputes.
        metric = _mean_metric("m1")
        exp = self._experiment(flag_key="calc-skip-existing", metrics=[metric])
        query_to = datetime.fromisoformat(_QUERY_TO)
        recalc_fp = compute_recalc_fingerprint(
            compute_metric_fingerprint(
                metric,
                exp.start_date,
                get_experiment_stats_method(exp),
                exp.exposure_criteria,
                only_count_matured_users=exp.only_count_matured_users,
            )
        )
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

        with patch("products.experiments.backend.temporal.recalculation_logic.ExperimentQueryRunner") as mock_runner:
            result = _calculate(exp.id, "m1", str(recalc.id), _QUERY_TO)

        mock_runner.assert_not_called()
        assert result.success is True
        # The existing row is left untouched: same id, same result.
        rows = ExperimentMetricResult.objects.filter(experiment=exp, metric_uuid="m1", query_to=query_to)
        assert rows.count() == 1
        row = rows.get()
        assert row.id == existing.id
        assert row.result == {"already": "computed"}

    def test_recomputes_when_existing_result_has_a_different_fingerprint(self):
        # A config change yields a different recalc fingerprint, so the existing row does not match and the
        # activity must recompute rather than reuse a stale result.
        metric = _mean_metric("m1")
        exp = self._experiment(flag_key="calc-skip-stale", metrics=[metric])
        query_to = datetime.fromisoformat(_QUERY_TO)
        ExperimentMetricResult.objects.create(
            experiment=exp,
            metric_uuid="m1",
            fingerprint="stale-fingerprint-from-old-config",
            query_from=query_to,
            query_to=query_to,
            status=ExperimentMetricResult.Status.COMPLETED,
            result={"stale": True},
        )
        recalc = self._recalc(exp, metric_uuids=["m1"])

        with patch("products.experiments.backend.temporal.recalculation_logic.ExperimentQueryRunner") as mock_runner:
            mock_runner.return_value.run.return_value.model_dump.return_value = {}
            _calculate(exp.id, "m1", str(recalc.id), _QUERY_TO)

        mock_runner.assert_called_once()

    def test_store_result_updates_existing_row_with_different_fingerprint_in_place(self):
        # The unique constraint is (experiment, metric_uuid, query_to); fingerprint is not part of it. A row may
        # already occupy that key under a different fingerprint (an earlier run written under the old per-run
        # scheme, or the timeseries workflow). _store_result must update that row in place, not insert a second
        # one and crash with IntegrityError. This is what unsticks experiments already collided in production.
        exp = self._experiment(flag_key="store-upsert-key", metrics=[_mean_metric("m1")])
        query_to = datetime.fromisoformat(_QUERY_TO)
        ExperimentMetricResult.objects.create(
            experiment=exp,
            metric_uuid="m1",
            fingerprint="legacy-fingerprint-from-a-prior-run",
            query_from=query_to,
            query_to=query_to,
            status=ExperimentMetricResult.Status.COMPLETED,
            result={"stale": True},
        )

        _store_result(
            experiment_id=exp.id,
            metric_uuid="m1",
            recalc_fp="new-deterministic-fingerprint",
            query_from=query_to,
            query_to=query_to,
            status=ExperimentMetricResult.Status.COMPLETED,
            result={"fresh": True},
            error_message=None,
        )

        rows = ExperimentMetricResult.objects.filter(experiment=exp, metric_uuid="m1", query_to=query_to)
        assert rows.count() == 1
        row = rows.get()
        assert row.fingerprint == "new-deterministic-fingerprint"
        assert row.result == {"fresh": True}

    @parameterized.expand(
        [
            # (name, metric_uuid, metrics_on_experiment, run_with_mocked_failure, expected_result_rows)
            # Discovery-step failure: m1 in the recalc's discovered set but absent from the experiment (deleted
            # between discovery and calc). No result row written, only metric_errors.
            ("discovery_failure", "m1", [], False, 0),
            # Calculation-step failure: m1 resolves, runner raises, writes both metric_errors and exactly one
            # FAILED result row (update_or_create overwrites on retry rather than inserting).
            ("calculation_failure", "m1", [_mean_metric("m1")], True, 1),
        ]
    )
    def test_retry_does_not_double_count(
        self, name: str, metric_uuid: str, metrics: list, mock_runner_failure: bool, expected_result_rows: int
    ):
        # Temporal retries the whole activity on transient failure. _store_result is idempotent (update_or_create
        # keyed on fingerprint + query_to) and metric_errors is keyed by metric_uuid, so a second run must leave
        # state identical to the first — no inflated counts, no duplicate result rows.
        exp = self._experiment(flag_key=f"retry-{name}", metrics=metrics)
        recalc = self._recalc(exp, metric_uuids=[metric_uuid])

        def _run() -> None:
            if mock_runner_failure:
                with patch(
                    "products.experiments.backend.temporal.recalculation_logic.ExperimentQueryRunner"
                ) as mock_runner:
                    mock_runner.return_value.run.side_effect = RuntimeError("kaboom")
                    # Calc-step failures now re-raise so Temporal can retry transient errors. The record is
                    # written before the re-raise, so the assertions below still hold across attempts.
                    with pytest.raises(RuntimeError, match="kaboom"):
                        _calculate(exp.id, metric_uuid, str(recalc.id), _QUERY_TO)
            else:
                _calculate(exp.id, metric_uuid, str(recalc.id), _QUERY_TO)

        _run()
        _run()  # simulated Temporal retry

        recalc.refresh_from_db()
        assert len(recalc.metric_errors) == 1
        assert metric_uuid in recalc.metric_errors
        # Exact count per case: 0 for discovery failures (no _store_result call), 1 for calc failures
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
        exp = self._experiment(flag_key=f"validation-{name}", metrics=[_mean_metric("m1")])
        recalc = self._recalc(exp, metric_uuids=["m1"])
        if build_kwargs.get("clear_query_to"):
            recalc.query_to = None
            recalc.save(update_fields=["query_to"])

        call_experiment_id = exp.id + build_kwargs.get("experiment_id_offset", 0)
        call_metric_uuid = build_kwargs.get("metric_uuid_override", "m1")
        call_query_to = build_kwargs.get("query_to_override", _QUERY_TO)

        with pytest.raises(ApplicationError) as exc_info:
            _calculate(call_experiment_id, call_metric_uuid, str(recalc.id), call_query_to)

        assert expected_fragment in str(exc_info.value)
        assert exc_info.value.non_retryable is True

    def test_unexpected_error_calls_capture_exception_and_caps_message(self):
        # Unexpected exceptions get captured to Sentry and re-raised for Temporal retry. The stored result row
        # carries the capped error message so the UI sees what happened even though the activity re-raised.
        exp = self._experiment(flag_key="calc-capture", metrics=[_mean_metric("m1")])
        recalc = self._recalc(exp, metric_uuids=["m1"])

        with (
            patch("products.experiments.backend.temporal.recalculation_logic.ExperimentQueryRunner") as mock_runner,
            patch("products.experiments.backend.temporal.recalculation_logic.capture_exception") as mock_capture,
        ):
            mock_runner.return_value.run.side_effect = RuntimeError("x" * 5000)
            with pytest.raises(RuntimeError):
                _calculate(exp.id, "m1", str(recalc.id), _QUERY_TO)

        assert mock_capture.called
        row = ExperimentMetricResult.objects.get(experiment=exp, metric_uuid="m1")
        assert row.status == ExperimentMetricResult.Status.FAILED
        assert row.error_message is not None
        assert len(row.error_message) <= 2000


@pytest.mark.django_db(transaction=True)
class TestMissingRecalcRow:
    # All three activities go through _get_recalc_state at the top. A missing row is deterministic
    # (bogus id, manual delete, or cascade from team/experiment) — every activity must fail non-retryable
    # so Temporal terminates instead of burning retries.
    @parameterized.expand(
        [
            ("discover", lambda bogus_id: _discover(bogus_id)),
            # mark_started satisfies the XOR guard so the call reaches _get_recalc_state.
            (
                "update_progress",
                lambda bogus_id: _update(RecalculationProgressUpdate(recalculation_id=bogus_id, mark_started=True)),
            ),
            ("calculate", lambda bogus_id: _calculate(1, "m1", bogus_id, _QUERY_TO)),
        ]
    )
    def test_fails_non_retryable(self, name: str, call_activity):
        bogus_id = "019e9af0-0000-7000-8000-000000000000"

        with pytest.raises(ApplicationError) as exc_info:
            call_activity(bogus_id)

        assert bogus_id in str(exc_info.value)
        assert "not found" in str(exc_info.value)
        assert exc_info.value.non_retryable is True


@contextmanager
def _record_captures():
    """Patch ph_scoped_capture so the analytics tests can assert the exact event name + properties
    without standing up a real PostHog client. Yields the list of captured capture(...) kwargs."""
    captured: list[dict] = []

    def _fake_capture(*args, **kwargs) -> None:
        captured.append(kwargs)

    @contextmanager
    def _fake_scoped():
        yield _fake_capture

    with patch(
        "products.experiments.backend.temporal.recalculation_logic.ph_scoped_capture",
        _fake_scoped,
    ):
        yield captured


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
            query_to=datetime.fromisoformat(_QUERY_TO),
        )

    def test_metric_finished_event_on_success(self):
        exp = self._experiment(flag_key="an-success", metrics=[_mean_metric("m1")])
        recalc = self._recalc(exp, metric_uuids=["m1"])

        with _record_captures() as captured:
            with patch(
                "products.experiments.backend.temporal.recalculation_logic.ExperimentQueryRunner"
            ) as mock_runner:
                mock_runner.return_value.run.return_value.model_dump.return_value = {}
                _calculate(exp.id, "m1", str(recalc.id), _QUERY_TO)

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
        assert "duration_ms" in props

    def test_metric_error_event_on_insufficient_data(self):
        exp = self._experiment(flag_key="an-error", metrics=[_mean_metric("m1")])
        recalc = self._recalc(exp, metric_uuids=["m1"])

        with _record_captures() as captured:
            with patch(
                "products.experiments.backend.temporal.recalculation_logic.ExperimentQueryRunner"
            ) as mock_runner:
                mock_runner.return_value.run.side_effect = StatisticError("not enough data")
                _calculate(exp.id, "m1", str(recalc.id), _QUERY_TO)

        assert len(captured) == 1
        props = captured[0]["properties"]
        assert captured[0]["event"] == "experiment metric error"
        assert props["error_type"] == "insufficient_data"
        assert props["error_message"] == "not enough data"
        assert props["execution_mode"] == "recalculation"

    def test_secondary_metric_is_not_marked_primary(self):
        # metric_type is now threaded through from the workflow's discovery output rather than re-derived
        # from a fresh DB lookup. The activity's caller (workflow) reads the value from
        # ExperimentMetricToRecalculate; tests pass it explicitly to exercise the same path.
        exp = self._experiment(flag_key="an-secondary", secondary=[_mean_metric("s1")])
        recalc = self._recalc(exp, metric_uuids=["s1"])

        with _record_captures() as captured:
            with patch(
                "products.experiments.backend.temporal.recalculation_logic.ExperimentQueryRunner"
            ) as mock_runner:
                mock_runner.return_value.run.return_value.model_dump.return_value = {}
                _calculate(exp.id, "s1", str(recalc.id), _QUERY_TO, metric_type="secondary")

        assert captured[0]["properties"]["is_primary"] is False

    def test_non_final_failure_emits_no_per_metric_event(self):
        # A non-final attempt re-raises for Temporal to retry; emitting there would double-count a
        # failure that may still succeed on a later attempt. Only the terminal attempt emits.
        exp = self._experiment(flag_key="an-transient", metrics=[_mean_metric("m1")])
        recalc = self._recalc(exp, metric_uuids=["m1"])

        with _record_captures() as captured:
            with patch(
                "products.experiments.backend.temporal.recalculation_logic.ExperimentQueryRunner"
            ) as mock_runner:
                mock_runner.return_value.run.side_effect = RuntimeError("kaboom")
                with pytest.raises(RuntimeError, match="kaboom"):
                    _calculate(exp.id, "m1", str(recalc.id), _QUERY_TO, is_final_attempt=False)

        assert captured == []

    @parameterized.expand(
        [
            ("wrapped_oom", ClickHouseQueryMemoryLimitExceeded(), "out_of_memory"),
            ("wrapped_timeout", ClickHouseQueryTimeOut(), "timeout"),
            ("ch_timeout_code", ServerException("timed out", code=159), "timeout"),
            ("ch_socket_timeout_code", ServerException("socket timed out", code=209), "timeout"),
            ("ch_memory_limit_code", ServerException("memory limit exceeded", code=241), "out_of_memory"),
            ("other", RuntimeError("kaboom"), "server_error"),
        ]
    )
    def test_terminal_failure_emits_metric_error_event(self, name, exc, expected_error_type):
        # On the terminal attempt (retries exhausted) an infra failure emits 'experiment metric error'
        # with the client-side error_type taxonomy, so recalc failures land on the same dashboards.
        # Covers both the wrapped exception classes and the raw ServerException code-lookup arm.
        exp = self._experiment(flag_key=f"an-terminal-{name}", metrics=[_mean_metric("m1")])
        recalc = self._recalc(exp, metric_uuids=["m1"])

        with _record_captures() as captured:
            with patch(
                "products.experiments.backend.temporal.recalculation_logic.ExperimentQueryRunner"
            ) as mock_runner:
                mock_runner.return_value.run.side_effect = exc
                with pytest.raises(type(exc)):
                    _calculate(exp.id, "m1", str(recalc.id), _QUERY_TO, is_final_attempt=True)

        assert len(captured) == 1
        assert captured[0]["event"] == "experiment metric error"
        props = captured[0]["properties"]
        assert props["error_type"] == expected_error_type
        assert props["execution_mode"] == "recalculation"

    def test_results_refresh_completed_event_on_finish(self):
        exp = self._experiment(flag_key="an-finish", metrics=[_mean_metric("m1")])
        recalc = self._recalc(exp, metric_uuids=["m1"])

        with _record_captures() as captured:
            _update(
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
        assert props["execution_mode"] == "recalculation"
        assert "total_duration_ms" in props

    def test_results_refresh_completed_not_re_emitted_on_retry(self):
        # mark_completed is first-write-wins; a retried finish activity must not re-fire the run-level event.
        exp = self._experiment(flag_key="an-finish-retry", metrics=[_mean_metric("m1")])
        recalc = self._recalc(exp, metric_uuids=["m1"])

        update = RecalculationProgressUpdate(
            recalculation_id=str(recalc.id), status="completed", mark_completed=True, succeeded_metrics=1
        )
        with _record_captures() as captured:
            _update(update)
            _update(update)  # simulated Temporal retry

        assert len(captured) == 1
