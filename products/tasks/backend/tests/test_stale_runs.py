import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from unittest.mock import AsyncMock, patch

from django.db import OperationalError
from django.test import SimpleTestCase, TestCase
from django.utils import timezone as django_timezone

from parameterized import parameterized
from temporalio.client import WorkflowExecutionStatus
from temporalio.service import RPCError, RPCStatusCode

from posthog.models import Organization, Team

from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.facade.contracts import SweptRunRow
from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.stale_runs import (
    StaleRule,
    StaleRunCount,
    SweepMode,
    collect_stale_live_runs,
    stale_rules,
    sweep_mode,
)
from products.tasks.backend.task_profiles import USER

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)
IDLE_TIMEOUT = timedelta(minutes=30)
CLOUD = TaskRun.Environment.CLOUD
LOCAL = TaskRun.Environment.LOCAL


_WORKFLOW_NOT_FOUND = RPCError("workflow not found", RPCStatusCode.NOT_FOUND, b"")


def _ago(**duration: int) -> datetime:
    return NOW - timedelta(**duration)


def _raise_or_return(answer: object) -> object:
    if isinstance(answer, Exception):
        raise answer
    return answer


class TestStaleRules(SimpleTestCase):
    @parameterized.expand(
        [
            ("fresh_heartbeat", CLOUD, _ago(minutes=5), None, _ago(hours=3), _ago(minutes=5), set()),
            ("quiet_within_the_grace", CLOUD, _ago(minutes=40), None, _ago(hours=3), _ago(minutes=40), set()),
            (
                "quiet_past_idle_and_grace",
                CLOUD,
                _ago(minutes=46),
                None,
                _ago(hours=3),
                _ago(minutes=46),
                {StaleRule.HEARTBEAT},
            ),
            (
                "never_heartbeated_counts_from_the_queue",
                CLOUD,
                None,
                _ago(minutes=46),
                _ago(hours=3),
                _ago(minutes=46),
                {StaleRule.HEARTBEAT},
            ),
            (
                "never_heartbeated_or_queued_counts_from_creation",
                LOCAL,
                None,
                None,
                _ago(minutes=46),
                _ago(minutes=46),
                {StaleRule.HEARTBEAT},
            ),
            ("resumed_run_ignores_its_old_heartbeat", CLOUD, _ago(hours=5), _ago(minutes=2), _ago(hours=6), NOW, set()),
            ("run_written_after_a_long_queue", CLOUD, None, _ago(hours=3), _ago(hours=3), _ago(minutes=2), set()),
            (
                "cloud_run_with_no_writes_for_a_day",
                CLOUD,
                _ago(hours=25),
                None,
                _ago(hours=26),
                _ago(hours=25),
                {StaleRule.HEARTBEAT, StaleRule.NO_WRITES_24H},
            ),
            (
                "heartbeating_cloud_run_with_an_old_write",
                CLOUD,
                _ago(minutes=1),
                None,
                _ago(hours=26),
                _ago(hours=25),
                {StaleRule.NO_WRITES_24H},
            ),
            (
                "local_run_never_meets_the_write_rule",
                LOCAL,
                _ago(minutes=1),
                None,
                _ago(hours=26),
                _ago(hours=25),
                set(),
            ),
        ]
    )
    def test_stale_rules(
        self,
        _name: str,
        environment: str,
        last_heartbeat_at: datetime | None,
        queued_at: datetime | None,
        created_at: datetime,
        updated_at: datetime,
        expected: set[StaleRule],
    ) -> None:
        rules = stale_rules(
            environment=environment,
            last_heartbeat_at=last_heartbeat_at,
            queued_at=queued_at,
            created_at=created_at,
            updated_at=updated_at,
            idle_timeout=IDLE_TIMEOUT,
            now=NOW,
        )

        assert rules == expected


class TestCollectStaleLiveRuns(TestCase):
    def setUp(self) -> None:
        self.team = Team.objects.create(organization=Organization.objects.create(name="Org"), name="Team")
        connect = patch("posthog.temporal.common.client.sync_connect").start()
        self.addCleanup(patch.stopall)
        self.describe_workflow = AsyncMock(side_effect=_WORKFLOW_NOT_FOUND)
        connect.return_value.get_workflow_handle.return_value.describe = self.describe_workflow

    def _run(
        self,
        *,
        status: str = TaskRun.Status.IN_PROGRESS,
        environment: str = CLOUD,
        profile: str | None = None,
        quiet_for: timedelta,
        idle_timeout_seconds: int | None = None,
        awaits_first_message: bool = False,
        no_write_for: timedelta | None = None,
        agent_status: str | None = TaskRun.AgentStatus.READY,
    ) -> TaskRun:
        task = Task.objects.create(
            team=self.team,
            title="Task",
            description="d",
            origin_product=Task.OriginProduct.USER_CREATED,
            profile=profile,
        )
        last_seen = django_timezone.now() - quiet_for
        run = TaskRun.objects.create(
            task=task,
            team=self.team,
            status=status,
            environment=environment,
            created_at=last_seen,
            last_heartbeat_at=last_seen if environment == CLOUD else None,
            agent_status=agent_status,
            state={
                **({"inactivity_timeout_seconds": idle_timeout_seconds} if idle_timeout_seconds else {}),
                **({"await_user_message": True} if awaits_first_message else {}),
            },
        )
        TaskRun.objects.filter(id=run.id).update(updated_at=django_timezone.now() - (no_write_for or quiet_for))
        return run

    def test_counts_only_live_runs_that_went_quiet_past_their_own_timeout(self) -> None:
        self._run(profile=USER.key, quiet_for=timedelta(hours=1), idle_timeout_seconds=600)
        self._run(profile=USER.key, quiet_for=timedelta(hours=1), idle_timeout_seconds=600)
        self._run(profile=USER.key, quiet_for=timedelta(hours=1), idle_timeout_seconds=7200)
        self._run(quiet_for=timedelta(seconds=5), idle_timeout_seconds=600)
        self._run(status=TaskRun.Status.COMPLETED, quiet_for=timedelta(hours=1), idle_timeout_seconds=600)
        self._run(
            status=TaskRun.Status.QUEUED, environment=LOCAL, quiet_for=timedelta(hours=1), idle_timeout_seconds=600
        )

        counts = collect_stale_live_runs()

        assert sorted(counts, key=lambda row: row.environment) == [
            StaleRunCount(profile=USER.key, environment=CLOUD, rule=StaleRule.HEARTBEAT, count=2),
            StaleRunCount(profile=None, environment=LOCAL, rule=StaleRule.HEARTBEAT, count=1),
        ]

    @parameterized.expand(
        [
            ("enforced_quiet_cloud_run", {USER.key: "enforce"}, {}, USER.key),
            ("shadow_mode", {USER.key: "shadow"}, {}, None),
            ("profile_not_in_the_payload", {"other": "enforce"}, {}, None),
            ("no_payload", None, {}, None),
            ("payload_sent_as_json", json.dumps({USER.key: "enforce"}), {}, USER.key),
            ("mode_that_does_not_exist", {USER.key: "enforced"}, {}, None),
            ("payload_that_is_not_a_mapping", ["enforce"], {}, None),
            ("run_that_showed_life", {USER.key: "enforce"}, {"quiet_for": timedelta(seconds=5)}, None),
            ("run_whose_workflow_just_started", {USER.key: "enforce"}, {"no_write_for": timedelta(seconds=5)}, None),
            ("run_still_setting_up", {USER.key: "enforce"}, {"agent_status": None}, None),
            (
                "run_whose_agent_is_starting",
                {USER.key: "enforce"},
                {"agent_status": TaskRun.AgentStatus.STARTING},
                None,
            ),
            (
                "run_stuck_in_setup",
                {USER.key: "enforce"},
                {"agent_status": None, "quiet_for": timedelta(hours=3)},
                USER.key,
            ),
            ("queued_run", {USER.key: "enforce"}, {"status": TaskRun.Status.QUEUED}, None),
            ("local_run", {USER.key: "enforce"}, {"environment": LOCAL}, None),
            (
                "warm_run_waiting_for_its_first_message_whose_workflow_is_gone",
                {USER.key: "enforce"},
                {"awaits_first_message": True},
                USER.key,
            ),
            ("task_without_a_profile", {USER.key: "enforce"}, {"profile": None}, None),
            ("task_without_a_profile_when_none_is_enforced", {"none": "enforce"}, {"profile": None}, "none"),
            (
                "run_that_heartbeats_but_wrote_nothing_for_a_day",
                {USER.key: "enforce"},
                {"quiet_for": timedelta(seconds=5), "no_write_for": timedelta(hours=25)},
                USER.key,
            ),
        ]
    )
    def test_sweep_ends_only_quiet_cloud_runs_of_enforced_profiles(
        self, _name: str, payload: object, run_overrides: dict, swept_profile: str | None
    ) -> None:
        run = self._run(
            **{"profile": USER.key, "quiet_for": timedelta(hours=1), "idle_timeout_seconds": 600, **run_overrides}
        )

        with patch("products.tasks.backend.stale_runs.posthoganalytics.get_feature_flag_payload", return_value=payload):
            rows = tasks_facade.sweep_stale_live_task_runs()

        run.refresh_from_db()
        assert (run.status == TaskRun.Status.FAILED) is (swept_profile is not None)
        assert rows == ([SweptRunRow(profile=swept_profile, count=1)] if swept_profile else [])

    @parameterized.expand(
        [
            ("still_running", SimpleNamespace(status=WorkflowExecutionStatus.RUNNING), False),
            ("finished", SimpleNamespace(status=WorkflowExecutionStatus.COMPLETED), True),
            ("terminated", SimpleNamespace(status=WorkflowExecutionStatus.TERMINATED), True),
            ("not_found", _WORKFLOW_NOT_FOUND, True),
            ("unknown_because_temporal_is_down", RPCError("unavailable", RPCStatusCode.UNAVAILABLE, b""), False),
            ("unknown_because_the_lookup_timed_out", TimeoutError("timed out"), False),
        ]
    )
    def test_sweep_ends_a_quiet_run_only_when_its_workflow_is_gone(
        self, _name: str, workflow: object, ended: bool
    ) -> None:
        runs = [self._run(profile=USER.key, quiet_for=timedelta(hours=1), idle_timeout_seconds=600) for _ in range(2)]
        self.describe_workflow.side_effect = lambda **_: _raise_or_return(workflow)

        with patch(
            "products.tasks.backend.stale_runs.posthoganalytics.get_feature_flag_payload",
            return_value={USER.key: "enforce"},
        ):
            tasks_facade.sweep_stale_live_task_runs()

        statuses = set(TaskRun.objects.filter(id__in=[run.id for run in runs]).values_list("status", flat=True))
        assert statuses == {TaskRun.Status.FAILED if ended else TaskRun.Status.IN_PROGRESS}

    def test_a_warm_run_waiting_for_its_first_message_is_left_while_its_workflow_runs(self) -> None:
        run = self._run(profile=USER.key, quiet_for=timedelta(hours=1), awaits_first_message=True)
        self.describe_workflow.side_effect = None
        self.describe_workflow.return_value = SimpleNamespace(status=WorkflowExecutionStatus.RUNNING)

        with patch(
            "products.tasks.backend.stale_runs.posthoganalytics.get_feature_flag_payload",
            return_value={USER.key: "enforce"},
        ):
            tasks_facade.sweep_stale_live_task_runs()

        run.refresh_from_db()
        assert run.status == TaskRun.Status.IN_PROGRESS

    @parameterized.expand(
        [
            ("that_still_heartbeats", timedelta(seconds=5)),
            ("that_went_silent", timedelta(hours=25)),
        ]
    )
    def test_sweep_ends_a_run_with_no_writes_for_a_day_even_if_its_workflow_runs(
        self, _name: str, quiet_for: timedelta
    ) -> None:
        run = self._run(profile=USER.key, quiet_for=quiet_for, no_write_for=timedelta(hours=25))
        self.describe_workflow.side_effect = None
        self.describe_workflow.return_value = SimpleNamespace(status=WorkflowExecutionStatus.RUNNING)

        with patch(
            "products.tasks.backend.stale_runs.posthoganalytics.get_feature_flag_payload",
            return_value={USER.key: "enforce"},
        ):
            tasks_facade.sweep_stale_live_task_runs()

        run.refresh_from_db()
        assert run.status == TaskRun.Status.FAILED

    def test_sweep_ends_at_most_its_cap_of_runs_in_one_pass(self) -> None:
        runs = [self._run(profile=USER.key, quiet_for=timedelta(hours=1), idle_timeout_seconds=600) for _ in range(3)]

        with (
            patch("products.tasks.backend.stale_runs.MAX_SWEEPS_PER_PASS", 2),
            patch(
                "products.tasks.backend.stale_runs.posthoganalytics.get_feature_flag_payload",
                return_value={USER.key: "enforce"},
            ),
        ):
            rows = tasks_facade.sweep_stale_live_task_runs()

        ended = TaskRun.objects.filter(id__in=[run.id for run in runs], status=TaskRun.Status.FAILED).count()
        assert ended == 2
        assert rows == [SweptRunRow(profile=USER.key, count=2)]

    def test_sweep_keeps_going_after_one_run_fails_to_end(self) -> None:
        runs = [self._run(profile=USER.key, quiet_for=timedelta(hours=1), idle_timeout_seconds=600) for _ in range(3)]
        end_run = tasks_facade.claim_and_fail_stale_run
        attempts: list[Any] = []

        def end_all_but_the_second(run_id: Any, *args: Any, **kwargs: Any) -> bool:
            attempts.append(run_id)
            if len(attempts) == 2:
                raise OperationalError("connection lost")
            return end_run(run_id, *args, **kwargs)

        with (
            patch("products.tasks.backend.facade.api.claim_and_fail_stale_run", side_effect=end_all_but_the_second),
            patch(
                "products.tasks.backend.stale_runs.posthoganalytics.get_feature_flag_payload",
                return_value={USER.key: "enforce"},
            ),
        ):
            rows = tasks_facade.sweep_stale_live_task_runs()

        ended = TaskRun.objects.filter(id__in=[run.id for run in runs], status=TaskRun.Status.FAILED).count()
        assert ended == 2
        assert rows == [SweptRunRow(profile=USER.key, count=2)]

    def test_sweep_leaves_runs_for_the_next_pass_once_its_flag_budget_is_spent(self) -> None:
        run = self._run(profile=USER.key, quiet_for=timedelta(hours=1), idle_timeout_seconds=600)

        with (
            patch("products.tasks.backend.stale_runs.SWEEP_MODE_LOOKUP_BUDGET_SECONDS", -1),
            patch(
                "products.tasks.backend.stale_runs.posthoganalytics.get_feature_flag_payload",
                return_value={USER.key: "enforce"},
            ),
        ):
            rows = tasks_facade.sweep_stale_live_task_runs()

        run.refresh_from_db()
        assert run.status == TaskRun.Status.IN_PROGRESS
        assert rows == []

    def test_sweep_leaves_runs_alone_when_the_flag_lookup_fails(self) -> None:
        run = self._run(profile=USER.key, quiet_for=timedelta(hours=1), idle_timeout_seconds=600)

        with patch(
            "products.tasks.backend.stale_runs.posthoganalytics.get_feature_flag_payload",
            side_effect=RuntimeError("flags are down"),
        ):
            rows = tasks_facade.sweep_stale_live_task_runs()

        run.refresh_from_db()
        assert run.status == TaskRun.Status.IN_PROGRESS
        assert rows == []

    @parameterized.expand(
        [
            ("resolved_mode", {USER.key: "enforce"}, SweepMode.ENFORCE),
            ("failed_lookup", RuntimeError("flags are down"), SweepMode.OFF),
        ]
    )
    def test_sweep_mode_is_kept_between_lookups(self, _name: str, first_answer: object, kept: SweepMode) -> None:
        with patch(
            "products.tasks.backend.stale_runs.posthoganalytics.get_feature_flag_payload",
            side_effect=[first_answer, {USER.key: "shadow"}],
        ):
            modes = [sweep_mode(USER.key, self.team), sweep_mode(USER.key, self.team)]

        assert modes == [kept, kept]

    @parameterized.expand([("read", "get"), ("write", "set")])
    def test_sweep_mode_is_resolved_when_the_cache_fails(self, _name: str, cache_call: str) -> None:
        with (
            patch(f"products.tasks.backend.stale_runs.cache.{cache_call}", side_effect=ConnectionError("cache down")),
            patch(
                "products.tasks.backend.stale_runs.posthoganalytics.get_feature_flag_payload",
                return_value={USER.key: "enforce"},
            ),
        ):
            assert sweep_mode(USER.key, self.team) == SweepMode.ENFORCE

    @parameterized.expand([("heartbeats", "last_heartbeat_at"), ("is_written", "updated_at")])
    def test_a_run_that_shows_life_after_the_scan_is_not_swept(self, _name: str, sign_of_life: str) -> None:
        run = self._run(profile=USER.key, quiet_for=timedelta(hours=1), idle_timeout_seconds=600)
        quiet_since = django_timezone.now() - timedelta(minutes=25)
        TaskRun.objects.filter(id=run.id).update(**{sign_of_life: django_timezone.now()})

        claimed = tasks_facade.claim_and_fail_stale_run(run.id, "quiet", quiet_since=quiet_since)

        run.refresh_from_db()
        assert claimed is False
        assert run.status == TaskRun.Status.IN_PROGRESS
