from datetime import UTC, date, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from django.test import TestCase

from posthog.models import Organization, Team

from products.managed_warehouse.backend.facade.contracts import (
    ManagedWarehouseSourceJobStatus,
    ManagedWarehouseSourceJobUpdate,
    ManagedWarehouseSourceJobWorkflow,
)
from products.managed_warehouse.backend.models import ManagedWarehouseSourceJob
from products.managed_warehouse.backend.source_job_state import (
    count_finished_source_jobs_by_day,
    list_latest_source_jobs,
    record_source_job_state,
)


class TestManagedWarehouseSourceJobState(TestCase):
    def setUp(self) -> None:
        organization = Organization.objects.create(name="org")
        self.team = Team.objects.create(organization=organization, name="team")
        self.schema_id = uuid4()
        self.started_at = datetime(2026, 8, 1, tzinfo=UTC)

    def _update(
        self,
        *,
        workflow_type: ManagedWarehouseSourceJobWorkflow,
        status: ManagedWarehouseSourceJobStatus,
        attempt_id: str,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
    ) -> ManagedWarehouseSourceJobUpdate:
        return ManagedWarehouseSourceJobUpdate(
            team_id=self.team.id,
            schema_ids=[self.schema_id],
            source_job_id="external-job-1",
            attempt_id=attempt_id,
            workflow_type=workflow_type,
            status=status,
            started_at=started_at or self.started_at,
            finished_at=finished_at,
        )

    def test_repeated_updates_change_one_workflow_attempt(self) -> None:
        running = self._update(
            workflow_type=ManagedWarehouseSourceJobWorkflow.COPY,
            status=ManagedWarehouseSourceJobStatus.RUNNING,
            attempt_id="external-job-1",
        )
        completed_at = self.started_at + timedelta(minutes=2)
        completed = self._update(
            workflow_type=ManagedWarehouseSourceJobWorkflow.COPY,
            status=ManagedWarehouseSourceJobStatus.COMPLETED,
            attempt_id="external-job-1",
            finished_at=completed_at,
        )

        record_source_job_state(running)
        record_source_job_state(completed)

        assert ManagedWarehouseSourceJob.all_teams.count() == 1
        [state] = list_latest_source_jobs(team_id=self.team.id, schema_ids=[self.schema_id])
        assert state.status == ManagedWarehouseSourceJobStatus.COMPLETED
        assert state.last_completed_at == completed_at

    def test_latest_attempt_keeps_the_previous_success_timestamp(self) -> None:
        completed_at = self.started_at + timedelta(minutes=2)
        record_source_job_state(
            self._update(
                workflow_type=ManagedWarehouseSourceJobWorkflow.COPY,
                status=ManagedWarehouseSourceJobStatus.COMPLETED,
                attempt_id="copy-1",
                finished_at=completed_at,
            )
        )
        register_started_at = self.started_at + timedelta(minutes=5)
        record_source_job_state(
            self._update(
                workflow_type=ManagedWarehouseSourceJobWorkflow.REGISTER,
                status=ManagedWarehouseSourceJobStatus.FAILED,
                attempt_id="register-2",
                started_at=register_started_at,
                finished_at=register_started_at + timedelta(minutes=1),
            )
        )

        [state] = list_latest_source_jobs(team_id=self.team.id, schema_ids=[self.schema_id])

        assert state.workflow_type == ManagedWarehouseSourceJobWorkflow.REGISTER
        assert state.status == ManagedWarehouseSourceJobStatus.FAILED
        assert state.last_completed_at == completed_at

    def test_child_environments_share_the_tenant_boundary_without_sharing_status(self) -> None:
        environment_a = Team.objects.create(
            organization=self.team.organization,
            parent_team=self.team,
            name="environment a",
        )
        environment_b = Team.objects.create(
            organization=self.team.organization,
            parent_team=self.team,
            name="environment b",
        )
        for environment, status in (
            (environment_a, ManagedWarehouseSourceJobStatus.COMPLETED),
            (environment_b, ManagedWarehouseSourceJobStatus.FAILED),
        ):
            record_source_job_state(
                ManagedWarehouseSourceJobUpdate(
                    team_id=environment.id,
                    schema_ids=[self.schema_id],
                    source_job_id="external-job-1",
                    attempt_id="attempt-1",
                    workflow_type=ManagedWarehouseSourceJobWorkflow.COPY,
                    status=status,
                    started_at=self.started_at,
                    finished_at=self.started_at + timedelta(minutes=1),
                )
            )

        [state_a] = list_latest_source_jobs(team_id=environment_a.id, schema_ids=[self.schema_id])
        [state_b] = list_latest_source_jobs(team_id=environment_b.id, schema_ids=[self.schema_id])

        assert state_a.team_id == self.team.id
        assert state_a.environment_id == environment_a.id
        assert state_a.status == ManagedWarehouseSourceJobStatus.COMPLETED
        assert state_b.environment_id == environment_b.id
        assert state_b.status == ManagedWarehouseSourceJobStatus.FAILED

    def _finish(self, attempt_id: str, status: ManagedWarehouseSourceJobStatus, finished_at: datetime) -> None:
        record_source_job_state(
            self._update(
                workflow_type=ManagedWarehouseSourceJobWorkflow.COPY,
                status=status,
                attempt_id=attempt_id,
                started_at=finished_at - timedelta(minutes=1),
                finished_at=finished_at,
            )
        )

    def test_groups_terminal_attempts_by_day_in_the_requested_timezone(self) -> None:
        los_angeles = ZoneInfo("America/Los_Angeles")
        # 05:00 UTC is 22:00 the previous evening in Los Angeles, so it must land on 07-13 there.
        self._finish("a", ManagedWarehouseSourceJobStatus.COMPLETED, datetime(2026, 7, 14, 5, tzinfo=UTC))
        self._finish("b", ManagedWarehouseSourceJobStatus.FAILED, datetime(2026, 7, 14, 6, tzinfo=UTC))
        self._finish("c", ManagedWarehouseSourceJobStatus.COMPLETED, datetime(2026, 7, 14, 9, tzinfo=UTC))
        self._finish("d", ManagedWarehouseSourceJobStatus.STALE, datetime(2026, 7, 14, 9, tzinfo=UTC))
        self._finish("e", ManagedWarehouseSourceJobStatus.COMPLETED, datetime(2026, 7, 20, tzinfo=UTC))
        self._finish("f", ManagedWarehouseSourceJobStatus.RUNNING, datetime(2026, 7, 14, 9, tzinfo=UTC))

        counts = count_finished_source_jobs_by_day(
            team_id=self.team.id,
            schema_ids=[self.schema_id],
            start=datetime(2026, 7, 13, tzinfo=los_angeles),
            end=datetime(2026, 7, 15, tzinfo=los_angeles),
            tz=los_angeles,
        )

        assert [(c.day, c.completed, c.failed) for c in counts] == [
            (date(2026, 7, 13), 1, 1),
            (date(2026, 7, 14), 1, 0),
        ]

    def test_only_counts_the_requested_schemas(self) -> None:
        self._finish("a", ManagedWarehouseSourceJobStatus.COMPLETED, datetime(2026, 7, 14, 9, tzinfo=UTC))

        counts = count_finished_source_jobs_by_day(
            team_id=self.team.id,
            schema_ids=[uuid4()],
            start=datetime(2026, 7, 14, tzinfo=UTC),
            end=datetime(2026, 7, 15, tzinfo=UTC),
            tz=UTC,
        )

        assert counts == []
