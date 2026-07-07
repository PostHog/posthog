from datetime import UTC, datetime

from freezegun import freeze_time
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from products.tasks.backend.logic.services.sandbox import SandboxConfig
from products.tasks.backend.logic.services.sandbox_usage import (
    close_sandbox_session,
    get_posthog_code_sandbox_usage_by_team,
    open_sandbox_session,
    record_task_run_user_activity,
)
from products.tasks.backend.models import SandboxSession, Task, TaskRun


def _config(**overrides) -> SandboxConfig:
    defaults: dict = {"name": "test-sandbox", "cpu_cores": 4.0, "memory_gb": 16.0, "ttl_seconds": 6 * 60 * 60}
    defaults.update(overrides)
    return SandboxConfig(**defaults)


class SandboxUsageBase(APIBaseTest):
    def _run(self, *, state: dict | None = None) -> TaskRun:
        task = Task.objects.create(team=self.team, title="t", description="")
        return TaskRun.objects.create(task=task, team=self.team, state=state or {})


class TestSandboxSessionWrites(SandboxUsageBase):
    def test_open_attributes_cold_runs_immediately(self):
        run = self._run()

        open_sandbox_session(run_id=run.id, sandbox_id="sb-cold", config=_config())

        session = SandboxSession.objects.get(sandbox_id="sb-cold")
        assert session.team_id == self.team.id
        assert session.task_run_id == run.id
        assert session.user_attributed_at is not None
        assert session.prewarmed is False
        assert (session.cpu_cores, session.memory_gb, session.ttl_seconds) == (4.0, 16.0, 21600)
        assert session.burstable is False
        assert session.cpu_request_cores is None

    def test_open_leaves_warm_runs_unattributed(self):
        run = self._run(state={"await_user_message": True, "prewarmed": True})

        open_sandbox_session(run_id=run.id, sandbox_id="sb-warm", config=_config())

        session = SandboxSession.objects.get(sandbox_id="sb-warm")
        assert session.user_attributed_at is None
        assert session.prewarmed is True

    def test_open_records_burstable_request_floors(self):
        run = self._run()

        open_sandbox_session(
            run_id=run.id,
            sandbox_id="sb-burst",
            config=_config(burstable_resources=True, cpu_request_cores=0.5, memory_request_mb=1024),
        )

        session = SandboxSession.objects.get(sandbox_id="sb-burst")
        assert session.burstable is True
        assert session.cpu_request_cores == 0.5
        assert session.memory_request_mb == 1024

    def test_open_retry_never_regresses_attribution(self):
        run = self._run(state={"await_user_message": True})
        open_sandbox_session(run_id=run.id, sandbox_id="sb-retry", config=_config())
        record_task_run_user_activity(run.id)
        attributed_at = SandboxSession.objects.get(sandbox_id="sb-retry").user_attributed_at
        assert attributed_at is not None

        # Activity retry re-runs the open with the run state still carrying the warm marker.
        open_sandbox_session(run_id=run.id, sandbox_id="sb-retry", config=_config())

        assert SandboxSession.objects.count() == 1
        assert SandboxSession.objects.get(sandbox_id="sb-retry").user_attributed_at == attributed_at

    def test_open_swallows_missing_run(self):
        open_sandbox_session(run_id="00000000-0000-0000-0000-000000000000", sandbox_id="sb-x", config=_config())

        assert SandboxSession.objects.count() == 0

    def test_close_stamps_once(self):
        run = self._run()
        open_sandbox_session(run_id=run.id, sandbox_id="sb-close", config=_config())

        close_sandbox_session("sb-close", reason=SandboxSession.EndedReason.CLEANUP)
        first = SandboxSession.objects.get(sandbox_id="sb-close")
        assert first.ended_at is not None
        assert first.ended_reason == SandboxSession.EndedReason.CLEANUP

        close_sandbox_session("sb-close", reason=SandboxSession.EndedReason.REAPED)
        again = SandboxSession.objects.get(sandbox_id="sb-close")
        assert again.ended_at == first.ended_at
        assert again.ended_reason == SandboxSession.EndedReason.CLEANUP

    def test_user_activity_stamps_open_sessions_only(self):
        run = self._run(state={"await_user_message": True})
        open_sandbox_session(run_id=run.id, sandbox_id="sb-a", config=_config())
        open_sandbox_session(run_id=run.id, sandbox_id="sb-b", config=_config())
        close_sandbox_session("sb-b", reason=SandboxSession.EndedReason.CLEANUP)

        record_task_run_user_activity(run.id)

        live = SandboxSession.objects.get(sandbox_id="sb-a")
        assert live.user_attributed_at is not None
        assert live.last_user_activity_at is not None
        ended = SandboxSession.objects.get(sandbox_id="sb-b")
        assert ended.user_attributed_at is None
        assert ended.last_user_activity_at is None

    def test_user_activity_keeps_first_attribution(self):
        run = self._run(state={"await_user_message": True})
        open_sandbox_session(run_id=run.id, sandbox_id="sb-msgs", config=_config())

        with freeze_time("2026-01-02T10:00:00Z"):
            record_task_run_user_activity(run.id)
        with freeze_time("2026-01-02T11:00:00Z"):
            record_task_run_user_activity(run.id)

        session = SandboxSession.objects.get(sandbox_id="sb-msgs")
        assert session.user_attributed_at == datetime(2026, 1, 2, 10, tzinfo=UTC)
        assert session.last_user_activity_at == datetime(2026, 1, 2, 11, tzinfo=UTC)

    def test_facade_signal_attributes_claimed_warm_run(self):
        """Claiming a warm run with the first user message starts the billable window."""
        from products.tasks.backend.facade import api as tasks_facade

        run = self._run(state={"await_user_message": True, "prewarmed": True})
        open_sandbox_session(run_id=run.id, sandbox_id="sb-claim", config=_config())
        assert SandboxSession.objects.get(sandbox_id="sb-claim").user_attributed_at is None

        with patch("products.tasks.backend.temporal.client.signal_task_followup_message"):
            assert tasks_facade.signal_task_run_user_message(
                run.id, run.task_id, self.team.id, content="hi", artifact_ids=[]
            )

        assert SandboxSession.objects.get(sandbox_id="sb-claim").user_attributed_at is not None


class TestSandboxUsageAggregation(SandboxUsageBase):
    BEGIN = datetime(2026, 1, 2, tzinfo=UTC)
    END = datetime(2026, 1, 3, tzinfo=UTC)

    def _session(self, **overrides) -> SandboxSession:
        run = self._run()
        defaults: dict = {
            "team": self.team,
            "task_run": run,
            "cpu_cores": 4.0,
            "memory_gb": 16.0,
            "ttl_seconds": 6 * 60 * 60,
            "created_at": datetime(2026, 1, 2, 1, tzinfo=UTC),
            "user_attributed_at": datetime(2026, 1, 2, 1, tzinfo=UTC),
            "ended_at": datetime(2026, 1, 2, 2, tzinfo=UTC),
        }
        defaults.update(overrides)
        defaults.setdefault("sandbox_id", f"sb-{SandboxSession.objects.count()}")
        return SandboxSession.objects.create(**defaults)

    def test_sums_attributed_window_with_resource_multipliers(self):
        # Attributed an hour after creation: only [01:30, 02:30) bills, not boot/pre-warm time.
        self._session(
            created_at=datetime(2026, 1, 2, 0, 30, tzinfo=UTC),
            user_attributed_at=datetime(2026, 1, 2, 1, 30, tzinfo=UTC),
            ended_at=datetime(2026, 1, 2, 2, 30, tzinfo=UTC),
        )

        usage = get_posthog_code_sandbox_usage_by_team(self.BEGIN, self.END)

        assert usage.seconds == [(self.team.id, 3600)]
        assert usage.cpu_core_seconds == [(self.team.id, 3600 * 4)]
        assert usage.memory_gib_seconds == [(self.team.id, 3600 * 16)]

    def test_apportions_sessions_spanning_period_boundaries(self):
        # Attributed the previous day, ends mid-period: only the in-period slice counts.
        self._session(
            created_at=datetime(2026, 1, 1, 20, tzinfo=UTC),
            user_attributed_at=datetime(2026, 1, 1, 22, tzinfo=UTC),
            ended_at=datetime(2026, 1, 2, 6, tzinfo=UTC),
        )

        usage = get_posthog_code_sandbox_usage_by_team(self.BEGIN, self.END)

        assert usage.seconds == [(self.team.id, 6 * 3600)]

    def test_never_closed_session_clamps_to_ttl(self):
        self._session(
            created_at=datetime(2026, 1, 2, 1, tzinfo=UTC),
            user_attributed_at=datetime(2026, 1, 2, 1, tzinfo=UTC),
            ended_at=None,
            ttl_seconds=6 * 60 * 60,
        )

        with freeze_time("2026-01-05T00:00:00Z"):
            usage = get_posthog_code_sandbox_usage_by_team(self.BEGIN, self.END)

        # Cleanup never ran; the sandbox died at created_at + 6h regardless.
        assert usage.seconds == [(self.team.id, 6 * 3600)]

    def test_live_session_clamps_to_now(self):
        self._session(
            created_at=datetime(2026, 1, 2, 1, tzinfo=UTC),
            user_attributed_at=datetime(2026, 1, 2, 1, tzinfo=UTC),
            ended_at=None,
        )

        with freeze_time("2026-01-02T03:00:00Z"):
            usage = get_posthog_code_sandbox_usage_by_team(self.BEGIN, self.END)

        assert usage.seconds == [(self.team.id, 2 * 3600)]

    def test_excludes_unattributed_and_out_of_period_sessions(self):
        self._session(user_attributed_at=None, ended_at=None, sandbox_id="sb-unattributed")
        self._session(
            created_at=datetime(2026, 1, 1, 1, tzinfo=UTC),
            user_attributed_at=datetime(2026, 1, 1, 1, tzinfo=UTC),
            ended_at=datetime(2026, 1, 1, 2, tzinfo=UTC),
            sandbox_id="sb-ended-before",
        )
        self._session(
            created_at=datetime(2026, 1, 3, 1, tzinfo=UTC),
            user_attributed_at=datetime(2026, 1, 3, 1, tzinfo=UTC),
            ended_at=datetime(2026, 1, 3, 2, tzinfo=UTC),
            sandbox_id="sb-after",
        )

        usage = get_posthog_code_sandbox_usage_by_team(self.BEGIN, self.END)

        assert usage.seconds == []
        assert usage.cpu_core_seconds == []
        assert usage.memory_gib_seconds == []

    def test_aggregates_multiple_sessions_per_team(self):
        self._session(sandbox_id="sb-1")  # 1h at 4 cores
        self._session(sandbox_id="sb-2", cpu_cores=8.0, memory_gb=32.0)  # 1h at 8 cores

        usage = get_posthog_code_sandbox_usage_by_team(self.BEGIN, self.END)

        assert usage.seconds == [(self.team.id, 2 * 3600)]
        assert usage.cpu_core_seconds == [(self.team.id, 3600 * 4 + 3600 * 8)]
        assert usage.memory_gib_seconds == [(self.team.id, 3600 * 16 + 3600 * 32)]
