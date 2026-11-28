"""Tests for discovery and the start and finish of a recalculation run."""

from datetime import timedelta

import pytest
import time_machine
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from parameterized import parameterized
from temporalio.exceptions import ApplicationError

from posthog.schema import PrecomputationMode

from posthog.models.instance_setting import get_instance_setting, override_instance_config
from posthog.models.team.extensions import get_or_create_team_extension

from products.experiments.backend.hogql_queries.experiment_query_runner import ExperimentQueryRunner
from products.experiments.backend.models.experiment import (
    Experiment,
    ExperimentMetricsRecalculation,
    ExperimentSavedMetric,
    ExperimentToSavedMetric,
)
from products.experiments.backend.models.team_experiments_config import TeamExperimentsConfig
from products.experiments.backend.recalculation.kill_switch import RECALCULATION_ENABLED_SETTING
from products.experiments.backend.temporal.models import RecalculationProgressUpdate
from products.experiments.backend.temporal.recalculation.run_state import RECALCULATION_PAUSED_ERROR_TYPE
from products.feature_flags.backend.models.feature_flag import FeatureFlag

from . import test_helpers


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

    def _recalc(
        self, exp: Experiment, trigger: str = ExperimentMetricsRecalculation.Trigger.MANUAL
    ) -> ExperimentMetricsRecalculation:
        return ExperimentMetricsRecalculation.objects.create(team=self.team, experiment=exp, trigger=trigger)

    def _attach_saved_metric(self, exp: Experiment, uuid: str, role: str) -> None:
        saved = ExperimentSavedMetric.objects.create(
            team=self.team,
            name=f"saved-{uuid}",
            query={"uuid": uuid, "kind": "ExperimentMetric", "metric_type": "mean"},
        )
        ExperimentToSavedMetric.objects.create(experiment=exp, saved_metric=saved, metadata={"type": role})

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
            (
                "legacy_metric_without_metric_type_skipped",
                [
                    {"uuid": "m1", "metric_type": "mean", "kind": "ExperimentMetric"},
                    {"uuid": "legacy", "kind": "ExperimentTrendsQuery"},
                ],
                [],
                [],
                {"m1"},
                {"primary"},
            ),
        ]
    )
    def test_discover_persists_metric_uuids(self, name: str, primary, secondary, saved, expected_uuids, expected_roles):
        exp = self._experiment(flag_key=f"discover-{name}")
        exp.metrics = primary
        exp.metrics_secondary = secondary
        exp.save()
        for uuid, role in saved:
            self._attach_saved_metric(exp, uuid, role)
        recalc = self._recalc(exp)

        metrics = test_helpers._discover(str(recalc.id))

        recalc.refresh_from_db()
        assert set(recalc.metric_uuids) == expected_uuids
        assert {m.metric_uuid for m in metrics} == expected_uuids
        assert {m.role for m in metrics} == expected_roles

    @parameterized.expand(
        [
            # name, activity queue flag, team_enabled, team_cuped, runtime_hours, funnel_order_type, route_check_fails, expected route
            ("eligible", "on", True, False, 36, "ordered", False, "precompute-q", None),
            ("team_disabled", "on", False, False, 36, "ordered", False, "activity-q", PrecomputationMode.DIRECT),
            ("below_min_runtime", "on", True, False, 6, "ordered", False, "activity-q", PrecomputationMode.DIRECT),
            # Exposures stay precomputable when only the metric events are not, so the scan covers the metric alone.
            ("metric_not_eligible", "on", True, False, 36, "unordered", False, "activity-q", None),
            ("team_cuped", "on", True, True, 36, "ordered", False, "activity-q", None),
            ("route_check_fails", "on", False, False, 36, "ordered", True, "precompute-q", None),
            ("flag_off", "off", True, False, 36, "ordered", False, None, None),
            ("flag_check_fails", "error", True, False, 36, "ordered", False, None, None),
        ]
    )
    @override_settings(
        EXPERIMENTS_RECALCULATION_ACTIVITY_TASK_QUEUE="activity-q",
        EXPERIMENTS_RECALCULATION_PRECOMPUTE_TASK_QUEUE="precompute-q",
    )
    @time_machine.travel("2026-04-30T12:00:00Z", tick=False)
    def test_discover_routes_each_metric(
        self,
        name: str,
        flag: str,
        team_enabled: bool,
        team_cuped: bool,
        runtime_hours: int,
        funnel_order_type: str,
        route_check_fails: bool,
        expected_task_queue: str | None,
        expected_mode: PrecomputationMode | None,
    ):
        exp = self._experiment(flag_key=f"route-{name}")
        exp.start_date = timezone.now() - timedelta(hours=runtime_hours)
        exp.metrics = [
            {
                "uuid": "m1",
                "kind": "ExperimentMetric",
                "metric_type": "funnel",
                "series": [{"kind": "EventsNode", "event": "purchase"}],
                "funnel_order_type": funnel_order_type,
            }
        ]
        exp.save()
        config = get_or_create_team_extension(self.team, TeamExperimentsConfig)
        config.experiment_precomputation_enabled = team_enabled
        config.default_cuped_enabled = team_cuped
        config.save()
        recalc = self._recalc(exp)

        with (
            patch(
                "products.experiments.backend.temporal.recalculation.routing.organization_flag_enabled",
                return_value=flag == "on",
                side_effect=Exception("flags down") if flag == "error" else None,
            ),
            patch(
                "products.experiments.backend.temporal.recalculation.routing.ExperimentQueryRunner",
                side_effect=Exception("boom") if route_check_fails else ExperimentQueryRunner,
            ) as runner,
            patch(
                "products.experiments.backend.temporal.recalculation.discovery.get_or_create_team_extension",
                wraps=get_or_create_team_extension,
            ) as config_read,
        ):
            metrics = test_helpers._discover(str(recalc.id))

        assert [(m.task_queue, m.precomputation_mode) for m in metrics] == [(expected_task_queue, expected_mode)]
        assert runner.called is (flag == "on")
        assert config_read.called is (flag == "on")

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
        returned = test_helpers._update(RecalculationProgressUpdate(recalculation_id=str(recalc.id), **update_kwargs))

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
            return test_helpers._update(
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

    @parameterized.expand([("pending_run_fails", False), ("started_run_continues", True)])
    def test_mark_started_while_recalculation_is_paused(self, _name: str, started_before_pause: bool):
        recalc = self._recalc(self._experiment(flag_key="progress-paused"))

        def _start() -> str | None:
            return test_helpers._update(
                RecalculationProgressUpdate(
                    recalculation_id=str(recalc.id),
                    status="in_progress",
                    total_metrics=1,
                    metric_uuids=["m1"],
                    mark_started=True,
                )
            )

        first = _start() if started_before_pause else None
        with override_instance_config(RECALCULATION_ENABLED_SETTING, False):
            if started_before_pause:
                assert _start() == first
            else:
                with pytest.raises(ApplicationError) as exc_info:
                    _start()
                assert exc_info.value.type == RECALCULATION_PAUSED_ERROR_TYPE
                assert exc_info.value.non_retryable

        recalc.refresh_from_db()
        assert recalc.status == ("in_progress" if started_before_pause else "failed")
        assert recalc.completed_at is None

    @parameterized.expand([("pending_run", "pending"), ("already_failed_run", "failed")])
    def test_discover_while_recalculation_is_paused_stops_before_reading_the_run(self, _name: str, status: str):
        recalc = self._recalc(self._experiment(flag_key="discover-paused"))
        recalc.status = status
        recalc.save(update_fields=["status"])

        with (
            override_instance_config(RECALCULATION_ENABLED_SETTING, False),
            CaptureQueriesContext(connection) as queries,
        ):
            get_instance_setting.cache_clear()  # type: ignore[attr-defined]
            with pytest.raises(ApplicationError) as exc_info:
                test_helpers._discover(str(recalc.id))

        assert exc_info.value.type == RECALCULATION_PAUSED_ERROR_TYPE
        assert exc_info.value.non_retryable
        other_queries = [q["sql"] for q in queries.captured_queries if "posthog_instancesetting" not in q["sql"]]
        assert [q.split(" ")[0] for q in other_queries] == ["UPDATE"]
        recalc.refresh_from_db()
        assert recalc.status == "failed"
        assert recalc.completed_at is None

    @parameterized.expand(
        [
            # name, set_completed_at — both force-fail shapes leave query_to NULL while discovery runs.
            # admin "Mark as failed" stamps completed_at; the staleness sweep deliberately leaves it NULL, so
            # a completed_at-only guard would miss the sweep. The status guard catches both.
            ("admin_sets_completed_at", True),
            ("sweep_leaves_completed_at_null", False),
        ]
    )
    @time_machine.travel("2026-06-23T05:00:00Z", tick=False)
    def test_mark_started_does_not_revive_a_force_failed_run(self, name: str, set_completed_at: bool):
        recalc = self._recalc(self._experiment(flag_key=f"progress-start-force-failed-{name}"))
        completed_at = timezone.now() if set_completed_at else None
        ExperimentMetricsRecalculation.objects.filter(id=recalc.id).update(
            status=ExperimentMetricsRecalculation.Status.FAILED, completed_at=completed_at
        )

        returned = test_helpers._update(
            RecalculationProgressUpdate(
                recalculation_id=str(recalc.id),
                status="in_progress",
                total_metrics=3,
                metric_uuids=["m1", "m2", "m3"],
                mark_started=True,
            )
        )

        recalc.refresh_from_db()
        # The run stays terminal: no revival, no started_at, query_to left NULL.
        assert recalc.status == ExperimentMetricsRecalculation.Status.FAILED
        assert recalc.completed_at == completed_at
        assert recalc.started_at is None
        assert recalc.query_to is None
        # query_to was never pinned, so the read-back returns None; the workflow's isinstance(str) check then
        # fails the run non-retryably instead of proceeding to calc activities on a dead run.
        assert returned is None

    @parameterized.expand(
        [
            # The workflow's finish write can carry either terminal status; neither may touch a tombstone.
            ("workflow_finishes_completed", "completed"),
            ("backstop_stamps_failed", "failed"),
        ]
    )
    @time_machine.travel("2026-06-23T05:00:00Z", tick=False)
    def test_mark_completed_does_not_revive_a_force_failed_run(self, name: str, finish_status: str):
        # The staleness sweep force-fails a run with completed_at left NULL, and its workflow cancel is
        # best-effort. If the workflow survives to its finish write, the tombstone must win: without the
        # status guard the write matches on completed_at IS NULL and either flips the tombstone to
        # COMPLETED (becoming the "latest terminal run" the API serves) or stamps completed_at, turning
        # an invisible tombstone into a displayable failed run.
        recalc = self._recalc(self._experiment(flag_key=f"progress-finish-force-failed-{name}"))
        pinned_query_to = timezone.now()
        ExperimentMetricsRecalculation.objects.filter(id=recalc.id).update(
            status=ExperimentMetricsRecalculation.Status.FAILED,
            completed_at=None,
            query_to=pinned_query_to,
            started_at=timezone.now(),
        )

        returned = test_helpers._update(
            RecalculationProgressUpdate(
                recalculation_id=str(recalc.id),
                status=finish_status,
                mark_completed=True,
            )
        )

        assert returned is None
        recalc.refresh_from_db()
        assert recalc.status == ExperimentMetricsRecalculation.Status.FAILED
        assert recalc.completed_at is None

    @time_machine.travel("2026-06-23T05:00:00Z", tick=False)
    def test_mark_started_returns_none_when_force_failed_after_query_to_pinned(self):
        # mark_started ran first and pinned query_to (run went IN_PROGRESS), then an admin force-failed it.
        # A retried mark_started loses the guard, but the read-back must NOT hand back the pinned query_to as a
        # string: that would pass the workflow's isinstance(str) check and let calc activities run ClickHouse
        # queries and persist results for a terminal, superseded run (they don't re-check terminal status).
        recalc = self._recalc(self._experiment(flag_key="progress-start-pinned-then-failed"))
        pinned_query_to = timezone.now()
        ExperimentMetricsRecalculation.objects.filter(id=recalc.id).update(
            status=ExperimentMetricsRecalculation.Status.FAILED,
            completed_at=timezone.now(),
            query_to=pinned_query_to,
            started_at=timezone.now(),
        )

        returned = test_helpers._update(
            RecalculationProgressUpdate(
                recalculation_id=str(recalc.id),
                status="in_progress",
                total_metrics=3,
                metric_uuids=["m1", "m2", "m3"],
                mark_started=True,
            )
        )

        # Terminal read-back returns None despite query_to being pinned, so the workflow fails the run.
        assert returned is None
        recalc.refresh_from_db()
        assert recalc.status == ExperimentMetricsRecalculation.Status.FAILED
        assert recalc.query_to == pinned_query_to

    @parameterized.expand(
        [
            # name, end_date_offset_days (None = running experiment), expect query_to == end_date
            ("running_uses_now", None, False),
            ("stopped_uses_end_date", -5, True),
            ("future_end_uses_now", 5, False),
        ]
    )
    @time_machine.travel("2026-06-23T05:00:00Z", tick=False)
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

        test_helpers._update(
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

    @parameterized.expand(
        [
            # trigger, expect_reuse: only metric-scoped triggers reuse the prior completed window.
            (ExperimentMetricsRecalculation.Trigger.METRIC_CONFIG_CHANGE, True),
            (ExperimentMetricsRecalculation.Trigger.MANUAL_RETRY, True),
            (ExperimentMetricsRecalculation.Trigger.HEAL_LATEST_RUN, True),
            (ExperimentMetricsRecalculation.Trigger.EXPERIMENT_CONFIG_CHANGE, False),
            (ExperimentMetricsRecalculation.Trigger.COLD_RUN, False),
            (ExperimentMetricsRecalculation.Trigger.SCHEDULED, False),
            (ExperimentMetricsRecalculation.Trigger.MANUAL, False),
            (ExperimentMetricsRecalculation.Trigger.AUTO_REFRESH, False),
        ]
    )
    @time_machine.travel("2026-06-23T05:00:00Z", tick=False)
    def test_mark_started_reuses_prior_window_only_for_metric_config_change(self, trigger: str, expect_reuse: bool):
        # A running experiment has no end_date, so advancing triggers pin now while metric_config_change copies
        # the latest completed run's query_to — the signal that keeps unchanged metrics on the cache.
        now = timezone.now()
        prior_window = now - timedelta(hours=6)
        exp = self._experiment(flag_key=f"reuse-{trigger}")
        ExperimentMetricsRecalculation.objects.create(
            team=self.team,
            experiment=exp,
            status=ExperimentMetricsRecalculation.Status.COMPLETED,
            query_to=prior_window,
            completed_at=prior_window,
        )
        recalc = self._recalc(exp, trigger=trigger)

        test_helpers._update(
            RecalculationProgressUpdate(
                recalculation_id=str(recalc.id),
                status="in_progress",
                total_metrics=1,
                metric_uuids=["m1"],
                mark_started=True,
            )
        )

        recalc.refresh_from_db()
        assert recalc.query_to == (prior_window if expect_reuse else now)

    @time_machine.travel("2026-06-23T05:00:00Z", tick=False)
    def test_mark_started_reuses_partial_failure_window(self):
        # A run where one metric failed is marked FAILED but stamps completed_at and holds result rows for the
        # metrics that succeeded. Reuse must anchor on that newest terminal window, not fall back to an older
        # fully-completed one — otherwise the good metrics' displayed results move backward.
        now = timezone.now()
        older_completed = now - timedelta(hours=12)
        newer_partial = now - timedelta(hours=2)
        exp = self._experiment(flag_key="reuse-partial-failure")
        ExperimentMetricsRecalculation.objects.create(
            team=self.team,
            experiment=exp,
            status=ExperimentMetricsRecalculation.Status.COMPLETED,
            query_to=older_completed,
            completed_at=older_completed,
        )
        ExperimentMetricsRecalculation.objects.create(
            team=self.team,
            experiment=exp,
            status=ExperimentMetricsRecalculation.Status.FAILED,
            query_to=newer_partial,
            completed_at=newer_partial,
        )
        recalc = self._recalc(exp, trigger=ExperimentMetricsRecalculation.Trigger.METRIC_CONFIG_CHANGE)

        test_helpers._update(
            RecalculationProgressUpdate(
                recalculation_id=str(recalc.id),
                status="in_progress",
                total_metrics=1,
                metric_uuids=["m1"],
                mark_started=True,
            )
        )

        recalc.refresh_from_db()
        assert recalc.query_to == newer_partial

    @time_machine.travel("2026-06-23T05:00:00Z", tick=False)
    def test_mark_started_does_not_reuse_window_before_start_date(self):
        # After a reset and relaunch the prior run's rows survive with a query_to from before the new start_date.
        # Reusing that cutoff would begin the window before the experiment exists, so advance to now instead.
        now = timezone.now()
        exp = self._experiment(flag_key="reuse-before-start")
        exp.start_date = now - timedelta(hours=1)
        exp.save(update_fields=["start_date"])
        ExperimentMetricsRecalculation.objects.create(
            team=self.team,
            experiment=exp,
            status=ExperimentMetricsRecalculation.Status.COMPLETED,
            query_to=now - timedelta(days=3),
            completed_at=now - timedelta(days=3),
        )
        recalc = self._recalc(exp, trigger=ExperimentMetricsRecalculation.Trigger.METRIC_CONFIG_CHANGE)

        test_helpers._update(
            RecalculationProgressUpdate(
                recalculation_id=str(recalc.id),
                status="in_progress",
                total_metrics=1,
                metric_uuids=["m1"],
                mark_started=True,
            )
        )

        recalc.refresh_from_db()
        assert recalc.query_to == now

    @time_machine.travel("2026-06-23T05:00:00Z", tick=False)
    def test_mark_started_metric_config_change_clamps_to_end_date_when_stopped(self):
        # A stopped experiment has a fixed window: even metric_config_change resolves to end_date, so a stale
        # prior window (recorded before the stop) can never push the recompute window past end_date.
        now = timezone.now()
        exp = self._experiment(flag_key="reuse-stopped")
        exp.end_date = now - timedelta(days=2)
        exp.save(update_fields=["end_date"])
        ExperimentMetricsRecalculation.objects.create(
            team=self.team,
            experiment=exp,
            status=ExperimentMetricsRecalculation.Status.COMPLETED,
            query_to=now - timedelta(days=1),
            completed_at=now - timedelta(days=1),
        )
        recalc = self._recalc(exp, trigger=ExperimentMetricsRecalculation.Trigger.METRIC_CONFIG_CHANGE)

        test_helpers._update(
            RecalculationProgressUpdate(
                recalculation_id=str(recalc.id),
                status="in_progress",
                total_metrics=1,
                metric_uuids=["m1"],
                mark_started=True,
            )
        )

        recalc.refresh_from_db()
        assert recalc.query_to == exp.end_date

    @time_machine.travel("2026-06-23T05:00:00Z", tick=False)
    def test_mark_started_metric_config_change_advances_when_no_prior_window(self):
        # First metric-scoped run: nothing to reuse, so it falls back to now rather than leaving query_to unset.
        now = timezone.now()
        exp = self._experiment(flag_key="reuse-no-prior")
        recalc = self._recalc(exp, trigger=ExperimentMetricsRecalculation.Trigger.METRIC_CONFIG_CHANGE)

        test_helpers._update(
            RecalculationProgressUpdate(
                recalculation_id=str(recalc.id),
                status="in_progress",
                total_metrics=1,
                metric_uuids=["m1"],
                mark_started=True,
            )
        )

        recalc.refresh_from_db()
        assert recalc.query_to == now

    def test_mark_completed_is_first_write_wins_on_retry(self):
        # Symmetric to mark_started: a retried finish activity must not re-stamp completed_at.
        recalc = self._recalc(self._experiment(flag_key="progress-retry-finish"))
        # A hard-killed final attempt can orphan a retry entry; finishing the run must sweep it.
        recalc.metric_retries = {"m1": {"attempt": 7, "max_attempts": 8}}
        recalc.save(update_fields=["metric_retries"])

        def _finish() -> str | None:
            return test_helpers._update(
                RecalculationProgressUpdate(
                    recalculation_id=str(recalc.id),
                    status="completed",
                    mark_completed=True,
                )
            )

        _finish()
        recalc.refresh_from_db()
        assert recalc.metric_retries == {}
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
            test_helpers._update(RecalculationProgressUpdate(recalculation_id=str(recalc.id), **flags))

        assert "exactly one of mark_started or mark_completed" in str(exc_info.value)
        assert exc_info.value.non_retryable is True
