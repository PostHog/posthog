from datetime import UTC, datetime, timedelta

from unittest.mock import patch

from django.test import SimpleTestCase, TestCase
from django.utils import timezone as django_timezone

from parameterized import parameterized

from posthog.models import Organization, Team

from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.facade.contracts import SweptRunRow
from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.stale_runs import StaleRule, StaleRunCount, collect_stale_live_runs, stale_rules
from products.tasks.backend.task_profiles import USER

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)
IDLE_TIMEOUT = timedelta(minutes=30)
CLOUD = TaskRun.Environment.CLOUD
LOCAL = TaskRun.Environment.LOCAL


def _ago(**duration: int) -> datetime:
    return NOW - timedelta(**duration)


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

    def _run(
        self,
        *,
        status: str = TaskRun.Status.IN_PROGRESS,
        environment: str = CLOUD,
        profile: str | None = None,
        quiet_for: timedelta,
        idle_timeout_seconds: int | None = None,
        awaits_first_message: bool = False,
        warm_activation_started: bool = False,
    ) -> TaskRun:
        task = Task.objects.create(
            team=self.team,
            title="Task",
            description="d",
            origin_product=Task.OriginProduct.USER_CREATED,
            profile=profile,
        )
        last_seen = django_timezone.now() - quiet_for
        return TaskRun.objects.create(
            task=task,
            team=self.team,
            status=status,
            environment=environment,
            created_at=last_seen,
            last_heartbeat_at=last_seen if environment == CLOUD else None,
            state={
                **({"inactivity_timeout_seconds": idle_timeout_seconds} if idle_timeout_seconds else {}),
                **({"await_user_message": True} if awaits_first_message else {}),
                **({"warm_activation_started": True} if warm_activation_started else {}),
            },
        )

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
            ("run_that_showed_life", {USER.key: "enforce"}, {"quiet_for": timedelta(seconds=5)}, None),
            ("queued_run", {USER.key: "enforce"}, {"status": TaskRun.Status.QUEUED}, None),
            ("local_run", {USER.key: "enforce"}, {"environment": LOCAL}, None),
            ("warm_run_waiting_for_its_first_message", {USER.key: "enforce"}, {"awaits_first_message": True}, None),
            (
                "warm_run_whose_activation_started",
                {USER.key: "enforce"},
                {"awaits_first_message": True, "warm_activation_started": True},
                USER.key,
            ),
            ("task_without_a_profile", {USER.key: "enforce"}, {"profile": None}, None),
            ("task_without_a_profile_when_none_is_enforced", {"none": "enforce"}, {"profile": None}, "none"),
        ]
    )
    def test_sweep_ends_only_quiet_cloud_runs_of_enforced_profiles(
        self, _name: str, payload: dict[str, str] | None, run_overrides: dict, swept_profile: str | None
    ) -> None:
        run = self._run(
            **{"profile": USER.key, "quiet_for": timedelta(hours=1), "idle_timeout_seconds": 600, **run_overrides}
        )

        with patch("products.tasks.backend.stale_runs.posthoganalytics.get_feature_flag_payload", return_value=payload):
            rows = tasks_facade.sweep_stale_live_task_runs()

        run.refresh_from_db()
        assert (run.status == TaskRun.Status.FAILED) is (swept_profile is not None)
        assert rows == ([SweptRunRow(profile=swept_profile, count=1)] if swept_profile else [])

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

    def test_a_run_that_heartbeats_after_the_scan_is_not_swept(self) -> None:
        run = self._run(profile=USER.key, quiet_for=timedelta(hours=1), idle_timeout_seconds=600)
        quiet_since = django_timezone.now() - timedelta(minutes=25)
        TaskRun.objects.filter(id=run.id).update(last_heartbeat_at=django_timezone.now())

        claimed = tasks_facade.claim_and_fail_stale_run(run.id, "quiet", quiet_since=quiet_since)

        run.refresh_from_db()
        assert claimed is False
        assert run.status == TaskRun.Status.IN_PROGRESS
