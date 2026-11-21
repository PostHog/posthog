from datetime import UTC, datetime, timedelta

from django.test import SimpleTestCase, TestCase
from django.utils import timezone as django_timezone

from parameterized import parameterized

from posthog.models import Organization, Team

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
            state={"inactivity_timeout_seconds": idle_timeout_seconds} if idle_timeout_seconds else {},
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
