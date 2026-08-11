from datetime import UTC, datetime, timedelta
from uuid import uuid4

from django.test import TestCase

from posthog.models import Organization, Team

from products.managed_warehouse.backend.facade.contracts import (
    ManagedWarehouseSourceJobStatus,
    ManagedWarehouseSourceJobUpdate,
    ManagedWarehouseSourceJobWorkflow,
)
from products.managed_warehouse.backend.models import ManagedWarehouseSourceJob
from products.managed_warehouse.backend.source_job_state import list_latest_source_jobs, record_source_job_state


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
