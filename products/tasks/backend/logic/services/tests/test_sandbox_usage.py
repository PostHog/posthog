from datetime import UTC, datetime, timedelta
from decimal import Decimal

from freezegun import freeze_time
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models.organization import Organization
from posthog.models.scoping import team_scope
from posthog.models.team.team import Team

from products.tasks.backend.logic.services.sandbox import Sandbox, SandboxConfig
from products.tasks.backend.logic.services.sandbox_pricing import ComputeRateCard, ComputeRateCardConfigurationError
from products.tasks.backend.logic.services.sandbox_usage import (
    close_sandbox_session,
    get_billable_sandbox_compute_usage_by_team,
    get_task_sandbox_usage_by_team,
    measure_task_run_cpu_attribution,
    open_sandbox_session,
    record_task_run_user_activity,
)
from products.tasks.backend.models import Loop, SandboxSession, Task, TaskClientProvenance, TaskRun


def _config(**overrides) -> SandboxConfig:
    defaults: dict = {"name": "test-sandbox", "cpu_cores": 4.0, "memory_gb": 16.0, "ttl_seconds": 6 * 60 * 60}
    defaults.update(overrides)
    return SandboxConfig(**defaults)


class SandboxUsageBase(APIBaseTest):
    def _run(self, *, state: dict | None = None, client_provenance: TaskClientProvenance | None = None) -> TaskRun:
        task = Task.objects.create(
            team=self.team,
            title="t",
            description="",
            origin_product=Task.OriginProduct.USER_CREATED,
            client_provenance=client_provenance,
        )
        return TaskRun.objects.create(task=task, team=self.team, state=state or {})


class TestSandboxSessionWrites(SandboxUsageBase):
    def test_open_attributes_cold_runs_immediately(self):
        run = self._run()
        measured_at = datetime(2026, 1, 2, 10, tzinfo=UTC)

        open_sandbox_session(
            run_id=run.id,
            sandbox_id="sb-cold",
            config=_config(vm_runtime=True),
            cpu_usage_attribution_usec=1_234_567,
            billed_cpu_usage_attribution_usec=1_500_000,
            cpu_usage_attribution_measured_at=measured_at,
        )

        session = SandboxSession.objects.unscoped().get(sandbox_id="sb-cold")
        assert session.team_id == self.team.id
        assert session.task_run_id == run.id
        assert session.origin_product == Task.OriginProduct.USER_CREATED
        assert session.user_attributed_at is not None
        assert session.prewarmed is False
        assert session.vm_runtime is True
        assert (session.cpu_cores, session.memory_gb, session.ttl_seconds) == (4.0, 16.0, 21600)
        assert session.burstable is False
        assert session.cpu_request_cores is None
        assert session.user_attributed_at == measured_at
        assert session.provider_cpu_usage_attribution_usec == 1_234_567
        assert session.provider_billed_cpu_usage_attribution_usec == 1_500_000
        assert session.provider_cpu_usage_attribution_measured_at == measured_at

    def test_open_leaves_warm_runs_unattributed(self):
        run = self._run(
            state={"await_user_message": True, "prewarmed": True},
            client_provenance=TaskClientProvenance.POSTHOG_DESKTOP,
        )

        open_sandbox_session(run_id=run.id, sandbox_id="sb-warm", config=_config())

        session = SandboxSession.objects.unscoped().get(sandbox_id="sb-warm")
        assert session.user_attributed_at is None
        assert session.prewarmed is True
        assert session.client_provenance == TaskClientProvenance.POSTHOG_DESKTOP

    def test_warm_claim_snapshots_provenance_set_after_provisioning(self):
        run = self._run(state={"await_user_message": True, "prewarmed": True})
        open_sandbox_session(run_id=run.id, sandbox_id="sb-warm-claim", config=_config(vm_runtime=False))
        Task.objects.filter(id=run.task_id).update(client_provenance=TaskClientProvenance.POSTHOG_DESKTOP)

        with patch.object(Sandbox, "get_by_id") as get_by_id:
            get_by_id.return_value.read_cpu_usage_usec.return_value = 2_345_678
            get_by_id.return_value.read_billed_cpu_usage_usec.return_value = 3_000_000
            cpu_attribution = measure_task_run_cpu_attribution(run.id, self.team.id)
        record_task_run_user_activity(run.id, self.team.id, cpu_attribution)

        session = SandboxSession.objects.unscoped().get(sandbox_id="sb-warm-claim")
        assert session.user_attributed_at is not None
        assert session.client_provenance == TaskClientProvenance.POSTHOG_DESKTOP
        assert session.provider_cpu_usage_attribution_usec == 2_345_678
        assert session.provider_billed_cpu_usage_attribution_usec == 3_000_000
        assert session.provider_cpu_usage_attribution_measured_at == session.user_attributed_at

    def test_warm_claim_keeps_provenance_snapshotted_at_provisioning(self):
        run = self._run(
            state={"await_user_message": True, "prewarmed": True},
            client_provenance=TaskClientProvenance.POSTHOG_DESKTOP,
        )
        open_sandbox_session(run_id=run.id, sandbox_id="sb-warm-snapshot", config=_config(vm_runtime=True))
        Task.objects.filter(id=run.task_id).update(client_provenance=None)

        with patch.object(Sandbox, "get_by_id", side_effect=RuntimeError("unavailable")):
            cpu_attribution = measure_task_run_cpu_attribution(run.id, self.team.id)
        record_task_run_user_activity(run.id, self.team.id, cpu_attribution)

        session = SandboxSession.objects.unscoped().get(sandbox_id="sb-warm-snapshot")
        assert session.user_attributed_at is not None
        assert session.client_provenance == TaskClientProvenance.POSTHOG_DESKTOP
        assert session.provider_cpu_usage_attribution_usec is None

    def test_reprovisioned_session_keeps_task_provenance_snapshot(self):
        run = self._run(client_provenance=TaskClientProvenance.POSTHOG_DESKTOP)
        open_sandbox_session(run_id=run.id, sandbox_id="sb-first", config=_config())
        resumed_run = run.task.create_run(extra_state={"resume_from_run_id": str(run.id)})
        open_sandbox_session(run_id=resumed_run.id, sandbox_id="sb-resumed", config=_config())

        Task.objects.filter(id=run.task_id).update(client_provenance=None)
        open_sandbox_session(run_id=run.id, sandbox_id="sb-first", config=_config(cpu_cores=2.0))

        first = SandboxSession.objects.unscoped().get(sandbox_id="sb-first")
        resumed = SandboxSession.objects.unscoped().get(sandbox_id="sb-resumed")
        assert first.client_provenance == TaskClientProvenance.POSTHOG_DESKTOP
        assert resumed.client_provenance == TaskClientProvenance.POSTHOG_DESKTOP

    @parameterized.expand(
        [
            ("gvisor", {}, 0.5, 1024),
            # VM memory can't burst — its effective request is the limit, and the ledger must
            # record what the provider reserved, not the generic floor.
            ("vm", {"vm_runtime": True}, 0.5, 16384),
            ("clamped_to_limit", {"cpu_cores": 0.25, "memory_gb": 0.5}, 0.25, 512),
        ]
    )
    def test_open_records_effective_burstable_request_floors(
        self, name, config_overrides, expected_cpu_cores, expected_memory_mb
    ):
        run = self._run()

        open_sandbox_session(
            run_id=run.id,
            sandbox_id=f"sb-burst-{name}",
            config=_config(burstable_resources=True, cpu_request_cores=0.5, memory_request_mb=1024, **config_overrides),
        )

        session = SandboxSession.objects.unscoped().get(sandbox_id=f"sb-burst-{name}")
        assert session.burstable is True
        assert session.cpu_request_cores == expected_cpu_cores
        assert session.memory_request_mb == expected_memory_mb

    def test_open_anchors_ttl_deadline_at_the_sandbox_creation_boundary(self):
        # The provider's TTL clock starts at Sandbox.create(), minutes before repo
        # setup finishes and the row is opened — the deadline must anchor there.
        run = self._run()
        boundary = datetime(2026, 1, 2, 9, tzinfo=UTC)

        open_sandbox_session(run_id=run.id, sandbox_id="sb-anchor", config=_config(), sandbox_created_at=boundary)

        session = SandboxSession.objects.unscoped().get(sandbox_id="sb-anchor")
        assert session.created_at == boundary
        assert session.ttl_expires_at == boundary + timedelta(hours=6)

    def test_open_records_vm_runtime(self):
        run = self._run()

        open_sandbox_session(run_id=run.id, sandbox_id="sb-vm", config=_config(vm_runtime=True))

        assert SandboxSession.objects.unscoped().get(sandbox_id="sb-vm").vm_runtime is True

    def test_open_retry_never_regresses_attribution(self):
        run = self._run(state={"await_user_message": True})
        open_sandbox_session(run_id=run.id, sandbox_id="sb-retry", config=_config())
        record_task_run_user_activity(run.id, self.team.id)
        attributed_at = SandboxSession.objects.unscoped().get(sandbox_id="sb-retry").user_attributed_at
        assert attributed_at is not None

        # Activity retry re-runs the open with the run state still carrying the warm marker.
        open_sandbox_session(run_id=run.id, sandbox_id="sb-retry", config=_config())

        assert SandboxSession.objects.unscoped().count() == 1
        assert SandboxSession.objects.unscoped().get(sandbox_id="sb-retry").user_attributed_at == attributed_at

    def test_open_swallows_missing_run(self):
        open_sandbox_session(run_id="00000000-0000-0000-0000-000000000000", sandbox_id="sb-x", config=_config())

        assert SandboxSession.objects.unscoped().count() == 0

    def test_close_stamps_once(self):
        run = self._run()
        open_sandbox_session(run_id=run.id, sandbox_id="sb-close", config=_config())

        close_sandbox_session("sb-close", reason=SandboxSession.EndedReason.CLEANUP)
        first = SandboxSession.objects.unscoped().get(sandbox_id="sb-close")
        assert first.ended_at is not None
        assert first.ended_reason == SandboxSession.EndedReason.CLEANUP

        close_sandbox_session("sb-close", reason=SandboxSession.EndedReason.REAPED)
        again = SandboxSession.objects.unscoped().get(sandbox_id="sb-close")
        assert again.ended_at == first.ended_at
        assert again.ended_reason == SandboxSession.EndedReason.CLEANUP

    @patch("products.tasks.backend.models.posthoganalytics.capture")
    def test_close_captures_analytics_once(self, mock_capture):
        run = self._run()
        open_sandbox_session(run_id=run.id, sandbox_id="sb-analytics", config=_config())
        record_task_run_user_activity(run.id, self.team.id)

        close_sandbox_session("sb-analytics", reason=SandboxSession.EndedReason.CLEANUP)
        close_sandbox_session("sb-analytics", reason=SandboxSession.EndedReason.REAPED)

        captured = [c for c in mock_capture.call_args_list if c.kwargs.get("event") == "sandbox_session_closed"]
        assert len(captured) == 1
        props = captured[0].kwargs["properties"]
        assert props["ended_reason"] == SandboxSession.EndedReason.CLEANUP
        assert props["runtime_seconds"] >= 0
        assert props["idle_seconds"] >= 0
        assert props["prewarmed"] is False
        assert props["origin_product"] == Task.OriginProduct.USER_CREATED

    def test_close_records_provider_cpu_usage(self):
        run = self._run()
        open_sandbox_session(run_id=run.id, sandbox_id="sb-usage", config=_config(vm_runtime=True))
        measured_at = datetime(2026, 1, 2, 11, tzinfo=UTC)

        close_sandbox_session(
            "sb-usage",
            reason=SandboxSession.EndedReason.CLEANUP,
            cpu_usage_usec=12_345_678,
            billed_cpu_usage_usec=15_000_000,
            cpu_usage_measured_at=measured_at,
        )

        session = SandboxSession.objects.unscoped().get(sandbox_id="sb-usage")
        assert session.provider_cpu_usage_usec == 12_345_678
        assert session.provider_billed_cpu_usage_usec == 15_000_000
        assert session.provider_usage_measured_at == measured_at

    def test_user_activity_stamps_open_sessions_only(self):
        run = self._run(state={"await_user_message": True})
        open_sandbox_session(run_id=run.id, sandbox_id="sb-a", config=_config())
        open_sandbox_session(run_id=run.id, sandbox_id="sb-b", config=_config())
        close_sandbox_session("sb-b", reason=SandboxSession.EndedReason.CLEANUP)

        record_task_run_user_activity(run.id, self.team.id)

        live = SandboxSession.objects.unscoped().get(sandbox_id="sb-a")
        assert live.user_attributed_at is not None
        assert live.last_user_activity_at is not None
        ended = SandboxSession.objects.unscoped().get(sandbox_id="sb-b")
        assert ended.user_attributed_at is None
        assert ended.last_user_activity_at is None

    def test_user_activity_keeps_first_attribution(self):
        run = self._run(state={"await_user_message": True})
        open_sandbox_session(run_id=run.id, sandbox_id="sb-msgs", config=_config())

        with freeze_time("2026-01-02T10:00:00Z"):
            record_task_run_user_activity(run.id, self.team.id)
        with freeze_time("2026-01-02T11:00:00Z"):
            record_task_run_user_activity(run.id, self.team.id)

        session = SandboxSession.objects.unscoped().get(sandbox_id="sb-msgs")
        assert session.user_attributed_at == datetime(2026, 1, 2, 10, tzinfo=UTC)
        assert session.last_user_activity_at == datetime(2026, 1, 2, 11, tzinfo=UTC)

    def test_user_activity_is_scoped_to_the_run_team(self):
        run = self._run(state={"await_user_message": True})
        open_sandbox_session(run_id=run.id, sandbox_id="sb-scoped", config=_config())
        other_org = Organization.objects.create(name="other")
        other_team = Team.objects.create(organization=other_org, name="other")

        record_task_run_user_activity(run.id, other_team.id)

        assert SandboxSession.objects.unscoped().get(sandbox_id="sb-scoped").user_attributed_at is None

    def test_facade_signal_leaves_attribution_to_delivery(self):
        from products.tasks.backend.facade import api as tasks_facade

        run = self._run(state={"await_user_message": True, "prewarmed": True})
        open_sandbox_session(run_id=run.id, sandbox_id="sb-claim", config=_config())
        assert SandboxSession.objects.unscoped().get(sandbox_id="sb-claim").user_attributed_at is None

        with patch("products.tasks.backend.temporal.client.signal_task_followup_message"):
            assert tasks_facade.signal_task_run_user_message(
                run.id, run.task_id, self.team.id, content="hi", artifact_ids=[]
            )

        assert SandboxSession.objects.unscoped().get(sandbox_id="sb-claim").user_attributed_at is None


class TestSandboxUsageAggregation(SandboxUsageBase):
    BEGIN = datetime(2026, 1, 2, tzinfo=UTC)
    END = datetime(2026, 1, 3, tzinfo=UTC)

    def _session(self, **overrides) -> SandboxSession:
        run = overrides.pop("task_run", None) or self._run()
        defaults: dict = {
            "team": self.team,
            "task_run": run,
            "origin_product": Task.OriginProduct.USER_CREATED,
            "cpu_cores": 4.0,
            "memory_gb": 16.0,
            "ttl_seconds": 6 * 60 * 60,
            "created_at": datetime(2026, 1, 2, 1, tzinfo=UTC),
            "user_attributed_at": datetime(2026, 1, 2, 1, tzinfo=UTC),
            "ended_at": datetime(2026, 1, 2, 2, tzinfo=UTC),
        }
        defaults.update(overrides)
        defaults.setdefault("sandbox_id", f"sb-{SandboxSession.objects.unscoped().count()}")
        defaults.setdefault("ttl_expires_at", defaults["created_at"] + timedelta(seconds=defaults["ttl_seconds"]))
        return SandboxSession.objects.unscoped().create(**defaults)

    def _loop_session(
        self, *, internal: bool, client_provenance: TaskClientProvenance | None = TaskClientProvenance.POSTHOG_DESKTOP
    ) -> SandboxSession:
        with team_scope(self.team.id):
            loop = Loop.objects.create(
                team=self.team,
                name="loop",
                instructions="run",
                runtime_adapter="claude",
                internal=internal,
                client_provenance=client_provenance,
            )
        task = Task.objects.create(
            team=self.team,
            title="loop run",
            description="",
            origin_product=Task.OriginProduct.LOOP,
            internal=True,
            loop=loop,
            client_provenance=client_provenance,
        )
        run = TaskRun.objects.create(task=task, team=self.team)
        return self._session(
            task_run=run,
            origin_product=Task.OriginProduct.LOOP,
            client_provenance=client_provenance,
        )

    def _rate(
        self,
        *,
        version: str = "v1",
        effective_at: datetime | None = None,
        expires_at: datetime | None = None,
        cpu_core_second_usd: Decimal = Decimal("0.001"),
        memory_gib_second_usd: Decimal = Decimal("0.0001"),
    ) -> ComputeRateCard:
        return ComputeRateCard(
            version=version,
            effective_at=effective_at or self.BEGIN,
            expires_at=expires_at,
            cpu_core_second_usd=cpu_core_second_usd,
            memory_gib_second_usd=memory_gib_second_usd,
        )

    def test_billable_compute_requires_trusted_desktop_user_created_snapshot(self):
        self._session(client_provenance=TaskClientProvenance.POSTHOG_DESKTOP)
        for origin in (Task.OriginProduct.SLACK, Task.OriginProduct.SIGNAL_REPORT, Task.OriginProduct.LOOP, None):
            self._session(client_provenance=TaskClientProvenance.POSTHOG_DESKTOP, origin_product=origin)
        self._session(client_provenance=None)

        usage = get_billable_sandbox_compute_usage_by_team(self.BEGIN, self.END, rate_cards=(self._rate(),))

        assert usage.cpu_millicore_seconds == [(self.team.id, 14_400_000)]
        assert usage.memory_mib_seconds == [(self.team.id, 58_982_400)]
        assert usage.credits == [(self.team.id, 2016)]

    def test_billable_compute_includes_user_loops_and_excludes_internal_loops(self):
        self._loop_session(internal=False)
        self._loop_session(internal=True)
        self._loop_session(internal=False, client_provenance=None)

        usage = get_billable_sandbox_compute_usage_by_team(self.BEGIN, self.END, rate_cards=(self._rate(),))

        assert usage.cpu_millicore_seconds == [(self.team.id, 14_400_000)]
        assert usage.credits == [(self.team.id, 2016)]

    def test_billable_compute_uses_session_snapshot_after_task_changes(self):
        session = self._session(client_provenance=TaskClientProvenance.POSTHOG_DESKTOP)
        Task.objects.filter(id=session.task_run.task_id).update(
            origin_product=Task.OriginProduct.SLACK, client_provenance=None
        )

        usage = get_billable_sandbox_compute_usage_by_team(self.BEGIN, self.END, rate_cards=(self._rate(),))

        assert usage.credits == [(self.team.id, 2016)]

    def test_exact_session_costs_aggregate_before_bankers_credit_rounding(self):
        for sandbox_id in ("sb-fraction-a", "sb-fraction-b"):
            self._session(
                sandbox_id=sandbox_id,
                client_provenance=TaskClientProvenance.POSTHOG_DESKTOP,
                cpu_cores=1,
                memory_gb=1,
                ended_at=datetime(2026, 1, 2, 1, 0, 1, tzinfo=UTC),
            )
        rate = self._rate(cpu_core_second_usd=Decimal("0.0025"), memory_gib_second_usd=Decimal("0.0025"))

        usage = get_billable_sandbox_compute_usage_by_team(self.BEGIN, self.END, rate_cards=(rate,))

        assert usage.credits == [(self.team.id, 1)]

    def test_integer_resource_units_round_only_after_exact_aggregation(self):
        for sandbox_id in ("sb-units-a", "sb-units-b"):
            self._session(
                sandbox_id=sandbox_id,
                client_provenance=TaskClientProvenance.POSTHOG_DESKTOP,
                cpu_request_cores=0.125,
                memory_request_mb=384,
                ended_at=self.BEGIN + timedelta(seconds=1),
                user_attributed_at=self.BEGIN,
            )

        usage = get_billable_sandbox_compute_usage_by_team(
            self.BEGIN, self.BEGIN + timedelta(microseconds=500_000), rate_cards=(self._rate(),)
        )

        assert usage.cpu_millicore_seconds == [(self.team.id, 125)]
        assert usage.memory_mib_seconds == [(self.team.id, 384)]

    def test_integer_resource_units_support_large_values(self):
        self._session(
            client_provenance=TaskClientProvenance.POSTHOG_DESKTOP,
            cpu_request_cores=999.999,
            memory_request_mb=1_048_576,
        )

        usage = get_billable_sandbox_compute_usage_by_team(self.BEGIN, self.END, rate_cards=(self._rate(),))

        assert usage.cpu_millicore_seconds == [(self.team.id, 3_599_996_400)]
        assert usage.memory_mib_seconds == [(self.team.id, 3_774_873_600)]

    def test_pre_effective_usage_reports_explicit_integer_zeros(self):
        self._session(client_provenance=TaskClientProvenance.POSTHOG_DESKTOP)

        usage = get_billable_sandbox_compute_usage_by_team(
            self.BEGIN, self.END, rate_cards=(self._rate(effective_at=self.BEGIN + timedelta(hours=3)),)
        )

        expected = [(self.team.id, 0)]
        assert usage.credits == expected
        assert usage.cpu_millicore_seconds == expected
        assert usage.memory_mib_seconds == expected
        assert all(type(value) is int for rows in usage.__dict__.values() for _, value in rows)

    def test_compute_before_first_rate_is_free_and_rate_changes_are_applied(self):
        self._session(
            client_provenance=TaskClientProvenance.POSTHOG_DESKTOP,
            cpu_cores=1,
            memory_gb=1,
            created_at=self.BEGIN,
            user_attributed_at=self.BEGIN,
            ended_at=self.BEGIN + timedelta(seconds=3),
        )
        boundary = self.BEGIN + timedelta(seconds=2)
        rates = (
            self._rate(effective_at=self.BEGIN + timedelta(seconds=1), expires_at=boundary),
            self._rate(
                version="v2",
                effective_at=boundary,
                cpu_core_second_usd=Decimal("0.002"),
                memory_gib_second_usd=Decimal("0.0002"),
            ),
        )

        usage = get_billable_sandbox_compute_usage_by_team(self.BEGIN, self.END, rate_cards=rates)

        assert usage.cpu_millicore_seconds == [(self.team.id, 2000)]

    def test_empty_rate_card_is_not_launched_but_invalid_configuration_fails(self):
        self._session(client_provenance=TaskClientProvenance.POSTHOG_DESKTOP)

        assert get_billable_sandbox_compute_usage_by_team(self.BEGIN, self.END, rate_cards=()).credits == []
        invalid = self._rate(cpu_core_second_usd=Decimal("0"))
        with self.assertRaises(ComputeRateCardConfigurationError):
            get_billable_sandbox_compute_usage_by_team(self.BEGIN, self.END, rate_cards=(invalid,))

    def test_sums_attributed_window_with_resource_multipliers(self):
        # Attributed an hour after creation: only [01:30, 02:30) bills, not boot/pre-warm time.
        self._session(
            created_at=datetime(2026, 1, 2, 0, 30, tzinfo=UTC),
            user_attributed_at=datetime(2026, 1, 2, 1, 30, tzinfo=UTC),
            ended_at=datetime(2026, 1, 2, 2, 30, tzinfo=UTC),
        )

        usage = get_task_sandbox_usage_by_team(self.BEGIN, self.END)

        assert usage.seconds == [(self.team.id, 3600)]
        assert usage.cpu_core_seconds == [(self.team.id, 3600 * 4)]
        assert usage.memory_gib_seconds == [(self.team.id, 3600 * 16)]

    def test_apportions_sessions_spanning_period_boundaries(self):
        # Attributed the previous day, ends mid-period: only the in-period slice counts.
        self._session(
            created_at=datetime(2026, 1, 1, 20, tzinfo=UTC),
            user_attributed_at=datetime(2026, 1, 1, 22, tzinfo=UTC),
            ended_at=datetime(2026, 1, 2, 6, tzinfo=UTC),
            ttl_seconds=24 * 60 * 60,
        )

        usage = get_task_sandbox_usage_by_team(self.BEGIN, self.END)

        assert usage.seconds == [(self.team.id, 6 * 3600)]

    def test_never_closed_session_clamps_to_ttl(self):
        self._session(
            created_at=datetime(2026, 1, 2, 1, tzinfo=UTC),
            user_attributed_at=datetime(2026, 1, 2, 1, tzinfo=UTC),
            ended_at=None,
            ttl_seconds=6 * 60 * 60,
        )

        with freeze_time("2026-01-05T00:00:00Z"):
            usage = get_task_sandbox_usage_by_team(self.BEGIN, self.END)

        # Cleanup never ran; the sandbox died at created_at + 6h regardless.
        assert usage.seconds == [(self.team.id, 6 * 3600)]

    def test_expired_open_sessions_are_excluded(self):
        # A row that never got a close stamp and whose TTL expired before the period
        # is dropped by the query's open-arm TTL bound, not just the Python clamp.
        self._session(
            created_at=datetime(2025, 12, 20, 1, tzinfo=UTC),
            user_attributed_at=datetime(2025, 12, 20, 1, tzinfo=UTC),
            ended_at=None,
        )

        usage = get_task_sandbox_usage_by_team(self.BEGIN, self.END)

        assert usage.seconds == []

    def test_late_close_clamps_to_ttl(self):
        # Cleanup stamped hours after the provider already killed the sandbox at created_at + 6h.
        self._session(
            created_at=datetime(2026, 1, 2, 1, tzinfo=UTC),
            user_attributed_at=datetime(2026, 1, 2, 1, tzinfo=UTC),
            ended_at=datetime(2026, 1, 2, 10, tzinfo=UTC),
            ttl_seconds=6 * 60 * 60,
        )

        usage = get_task_sandbox_usage_by_team(self.BEGIN, self.END)

        assert usage.seconds == [(self.team.id, 6 * 3600)]

    @parameterized.expand([("hogland", 9 * 3600), (None, 6 * 3600)])
    def test_ttl_clamp_skips_hogland_but_holds_for_modal(self, sandbox_backend, expected_seconds):
        # Hogland's ttl_seconds is an idle timeout that every request extends, so a box can
        # end well after created_at + ttl_seconds; its billed window must keep the true end.
        # Modal's hard TTL is a kill deadline, so a Modal row still clamps to it.
        self._session(
            created_at=datetime(2026, 1, 2, 1, tzinfo=UTC),
            user_attributed_at=datetime(2026, 1, 2, 1, tzinfo=UTC),
            ended_at=datetime(2026, 1, 2, 10, tzinfo=UTC),
            ttl_seconds=6 * 60 * 60,
            sandbox_backend=sandbox_backend,
        )

        usage = get_task_sandbox_usage_by_team(self.BEGIN, self.END)

        assert usage.seconds == [(self.team.id, expected_seconds)]

    @parameterized.expand([("hogland", 24 * 3600), (None, None)])
    def test_open_session_past_its_ttl_bills_for_hogland_but_not_modal(self, sandbox_backend, expected_seconds):
        # An open hogland box keeps extending its idle TTL, so ttl_expires_at can fall before
        # the period while the box still runs. The open-arm TTL bound would drop it, so a
        # hogland arm keeps it and bills the whole period. A Modal row with the same
        # expired-TTL shape stays excluded, since its TTL is a hard kill deadline.
        self._session(
            created_at=datetime(2025, 12, 20, 1, tzinfo=UTC),
            user_attributed_at=datetime(2025, 12, 20, 1, tzinfo=UTC),
            ended_at=None,
            ttl_seconds=6 * 60 * 60,
            sandbox_backend=sandbox_backend,
        )

        with freeze_time("2026-01-05T00:00:00Z"):
            usage = get_task_sandbox_usage_by_team(self.BEGIN, self.END)

        if expected_seconds is None:
            assert usage.seconds == []
        else:
            assert usage.seconds == [(self.team.id, expected_seconds)]

    def test_live_session_clamps_to_now(self):
        self._session(
            created_at=datetime(2026, 1, 2, 1, tzinfo=UTC),
            user_attributed_at=datetime(2026, 1, 2, 1, tzinfo=UTC),
            ended_at=None,
        )

        with freeze_time("2026-01-02T03:00:00Z"):
            usage = get_task_sandbox_usage_by_team(self.BEGIN, self.END)

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

        usage = get_task_sandbox_usage_by_team(self.BEGIN, self.END)

        assert usage.seconds == []
        assert usage.cpu_core_seconds == []
        assert usage.memory_gib_seconds == []

    def test_aggregates_multiple_sessions_per_team(self):
        self._session(sandbox_id="sb-1")  # 1h at 4 cores
        self._session(sandbox_id="sb-2", cpu_cores=8.0, memory_gb=32.0)  # 1h at 8 cores

        usage = get_task_sandbox_usage_by_team(self.BEGIN, self.END)

        assert usage.seconds == [(self.team.id, 2 * 3600)]
        assert usage.cpu_core_seconds == [(self.team.id, 3600 * 4 + 3600 * 8)]
        assert usage.memory_gib_seconds == [(self.team.id, 3600 * 16 + 3600 * 32)]
