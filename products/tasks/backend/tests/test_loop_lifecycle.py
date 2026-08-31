import uuid
from datetime import timedelta

from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from posthog.models import Integration, Organization, Team, User

from products.tasks.backend.facade import api as tasks_api
from products.tasks.backend.facade.contracts import (
    AdvanceStagedTaskInput,
    CapabilityManifestDTO,
    CreateStagedTaskInput,
    PublicationLeaseReservationDTO,
    RepositoryBaseBindingDTO,
    RepositoryGrantBindingDTO,
)
from products.tasks.backend.loop_lifecycle import (
    DISABLED_REASON_OWNER_DEACTIVATED,
    DISABLED_REASON_OWNER_REMOVED,
    pause_loops_for_deactivated_user,
    pause_loops_for_removed_member,
)
from products.tasks.backend.models import Loop, Task, TaskPublicationLease, TaskRun, TaskStagedRunTransition

LIFECYCLE_MODULE = "products.tasks.backend.loop_lifecycle"


@override_settings(GITHUB_APP_SLUG="posthog")
class TestPauseLoopsForDeactivatedUser(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create_user(email="owner@example.com", first_name="Owner", password="password")
        self.github_integration = Integration.objects.create(
            team=self.team,
            kind=Integration.IntegrationKind.GITHUB,
            integration_id="staged-installation-1",
            config={"installation_id": "staged-installation-1"},
            errors="",
        )

    def _loop(self, **overrides) -> Loop:
        defaults = {
            "team": self.team,
            "created_by": self.user,
            "name": "Daily digest",
            "instructions": "Summarize",
            "runtime_adapter": "claude",
            "model": "claude-sonnet-5",
            "enabled": True,
        }
        defaults.update(overrides)
        return Loop.objects.unscoped().create(**defaults)

    def _staged_execution_run(self, loop: Loop) -> tuple[TaskRun, TaskPublicationLease, TaskStagedRunTransition]:
        caller_id = uuid.uuid4()
        created = tasks_api.create_staged_task(
            CreateStagedTaskInput(
                team_id=self.team.id,
                caller_id=caller_id,
                actor_id=self.user.id,
                idempotency_key="loop-staged-analysis",
                origin_product=Task.OriginProduct.LOOP,
                title="Analyze loop change",
                description="Analyze before execution.",
                repository="posthog/posthog",
                repository_grant=RepositoryGrantBindingDTO(
                    repository="posthog/posthog",
                    github_integration_id=self.github_integration.id,
                    github_installation_id="staged-installation-1",
                    grant_version="1",
                ),
                repository_base=RepositoryBaseBindingDTO(
                    repository="posthog/posthog", base_sha="a" * 40, base_branch="main"
                ),
                analysis_manifest=CapabilityManifestDTO(version=1, phase="analysis", capabilities=("read",)),
            )
        )
        source_run = TaskRun.objects.get(id=created.analysis_run_id)
        source_run.state["snapshot_external_id"] = "loop-analysis-snapshot"
        source_run.state["sandbox_backend"] = "modal"
        source_run.save(update_fields=["state", "updated_at"])
        advanced = tasks_api.advance_staged_task(
            AdvanceStagedTaskInput(
                team_id=self.team.id,
                caller_id=caller_id,
                task_id=created.task_id,
                source_run_id=created.analysis_run_id,
                idempotency_key="loop-staged-execution",
                execution_manifest=CapabilityManifestDTO(version=1, phase="execution", capabilities=("read", "draft")),
                reservation=PublicationLeaseReservationDTO(
                    logical_artifact_key="loop-artifact",
                    action_key="loop-action",
                    repository="posthog/posthog",
                    base_sha="a" * 40,
                    base_branch="main",
                    commit_message="Create draft",
                    pr_title="Draft",
                    pr_body="",
                    github_integration_id=self.github_integration.id,
                    github_installation_id="staged-installation-1",
                    grant_version="1",
                    starts_before=timezone.now() + timedelta(minutes=4),
                    expires_at=timezone.now() + timedelta(minutes=5),
                ),
            )
        )
        task = Task.objects.get(id=created.task_id)
        task.loop = loop
        task.save(update_fields=["loop", "updated_at"])
        source_run.status = TaskRun.Status.COMPLETED
        source_run.save(update_fields=["status", "updated_at"])
        execution_run = TaskRun.objects.get(id=advanced.execution_run_id)
        execution_run.state["loop_id"] = str(loop.id)
        execution_run.status = TaskRun.Status.IN_PROGRESS
        execution_run.save(update_fields=["state", "status", "updated_at"])
        assert advanced.publication_lease_id is not None
        return (
            execution_run,
            TaskPublicationLease.objects.for_team(self.team.id).get(id=advanced.publication_lease_id),
            TaskStagedRunTransition.objects.for_team(self.team.id).get(id=advanced.transition_id),
        )

    @patch(f"{LIFECYCLE_MODULE}.pause_loop_schedules")
    @patch(f"{LIFECYCLE_MODULE}.dispatch_loop_event")
    def test_deactivation_pauses_records_reason_and_notifies(self, mock_dispatch, _mock_pause):
        loop = self._loop()

        pause_loops_for_deactivated_user(self.user.id)

        loop.refresh_from_db()
        self.assertFalse(loop.enabled)
        self.assertEqual(loop.disabled_reason, DISABLED_REASON_OWNER_DEACTIVATED)
        reasons = [call.args[2].get("reason") for call in mock_dispatch.call_args_list if len(call.args) >= 3]
        self.assertIn(DISABLED_REASON_OWNER_DEACTIVATED, reasons)

    @patch(f"{LIFECYCLE_MODULE}.pause_loop_schedules")
    @patch(f"{LIFECYCLE_MODULE}.dispatch_loop_event")
    @patch(f"{LIFECYCLE_MODULE}.signal_loop_run_cancelled")
    def test_deactivation_cancels_and_signals_in_flight_runs(self, mock_signal, _mock_dispatch, _mock_pause):
        # Cancelling the DB row isn't enough: the live sandbox must be told to stop, or it runs to
        # completion under the deactivated owner's revoked credentials. Deactivation must signal each run.
        loop = self._loop()
        task = Task.objects.create(
            team=self.team,
            created_by=self.user,
            title="Active",
            description="d",
            origin_product=Task.OriginProduct.LOOP,
            internal=True,
        )
        run = task.create_run(mode="background", extra_state={"loop_id": str(loop.id)})
        run.status = TaskRun.Status.IN_PROGRESS
        run.save(update_fields=["status", "updated_at"])

        pause_loops_for_deactivated_user(self.user.id)

        run.refresh_from_db()
        self.assertEqual(run.status, TaskRun.Status.CANCELLED)
        mock_signal.assert_called_once_with(run.workflow_id)

    @patch(f"{LIFECYCLE_MODULE}.pause_loop_schedules")
    @patch(f"{LIFECYCLE_MODULE}.dispatch_loop_event")
    @patch(f"{LIFECYCLE_MODULE}.signal_loop_run_cancelled")
    def test_deactivation_revokes_staged_execution_before_a_failed_signal(
        self, mock_signal, _mock_dispatch, _mock_pause
    ) -> None:
        loop = self._loop()
        run, lease, transition = self._staged_execution_run(loop)

        def signal_and_fail(workflow_id: str) -> None:
            self.assertEqual(workflow_id, run.workflow_id)
            lease.refresh_from_db()
            transition.refresh_from_db()
            self.assertEqual(lease.status, TaskPublicationLease.Status.REVOKED)
            self.assertEqual(transition.status, TaskStagedRunTransition.Status.CANCELLED)
            raise RuntimeError("Temporal unavailable")

        mock_signal.side_effect = signal_and_fail

        pause_loops_for_deactivated_user(self.user.id)

        run.refresh_from_db()
        self.assertEqual(run.status, TaskRun.Status.CANCELLED)
        lease.refresh_from_db()
        transition.refresh_from_db()
        self.assertEqual(lease.status, TaskPublicationLease.Status.REVOKED)
        self.assertEqual(transition.status, TaskStagedRunTransition.Status.CANCELLED)

    @patch(f"{LIFECYCLE_MODULE}.pause_loop_schedules")
    @patch(f"{LIFECYCLE_MODULE}.dispatch_loop_event")
    @patch(f"{LIFECYCLE_MODULE}.signal_loop_run_cancelled")
    def test_deactivation_revokes_a_taken_over_staged_execution_before_a_failed_signal(
        self, mock_signal, _mock_dispatch, _mock_pause
    ) -> None:
        loop = self._loop()
        run, lease, transition = self._staged_execution_run(loop)
        new_owner = User.objects.create_user(email="new-owner@example.com", first_name="New", password="password")
        self.organization.members.add(new_owner)
        loop.created_by = new_owner
        loop.save(update_fields=["created_by", "updated_at"])

        def signal_and_fail(workflow_id: str) -> None:
            self.assertEqual(workflow_id, run.workflow_id)
            lease.refresh_from_db()
            transition.refresh_from_db()
            self.assertEqual(lease.status, TaskPublicationLease.Status.REVOKED)
            self.assertEqual(transition.status, TaskStagedRunTransition.Status.CANCELLED)
            raise RuntimeError("Temporal unavailable")

        mock_signal.side_effect = signal_and_fail

        pause_loops_for_deactivated_user(self.user.id)

        run.refresh_from_db()
        self.assertEqual(run.status, TaskRun.Status.CANCELLED)
        lease.refresh_from_db()
        transition.refresh_from_db()
        self.assertEqual(lease.status, TaskPublicationLease.Status.REVOKED)
        self.assertEqual(transition.status, TaskStagedRunTransition.Status.CANCELLED)

    @patch(f"{LIFECYCLE_MODULE}.pause_loop_schedules")
    @patch(f"{LIFECYCLE_MODULE}.dispatch_loop_event")
    @patch(f"{LIFECYCLE_MODULE}.signal_loop_run_cancelled")
    def test_member_removal_pauses_loops_and_cancels_runs_in_that_org_only(
        self, mock_signal, _mock_dispatch, _mock_pause
    ):
        # Offboarding leaves is_active=True, so in-flight runs would otherwise keep minting the former
        # org's credentials. Removal must pause the loop and cancel its run — but only in that org.
        loop = self._loop()
        task = Task.objects.create(
            team=self.team,
            created_by=self.user,
            title="Active",
            description="d",
            origin_product=Task.OriginProduct.LOOP,
            internal=True,
        )
        run = task.create_run(mode="background", extra_state={"loop_id": str(loop.id)})
        run.status = TaskRun.Status.IN_PROGRESS
        run.save(update_fields=["status", "updated_at"])

        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")
        other_loop = self._loop(team=other_team)

        pause_loops_for_removed_member(self.user.id, str(self.organization.id))

        loop.refresh_from_db()
        self.assertFalse(loop.enabled)
        self.assertEqual(loop.disabled_reason, DISABLED_REASON_OWNER_REMOVED)
        run.refresh_from_db()
        self.assertEqual(run.status, TaskRun.Status.CANCELLED)
        mock_signal.assert_called_once_with(run.workflow_id)
        other_loop.refresh_from_db()
        self.assertTrue(other_loop.enabled)

    @patch(f"{LIFECYCLE_MODULE}.pause_loop_schedules")
    @patch(f"{LIFECYCLE_MODULE}.dispatch_loop_event")
    @patch(f"{LIFECYCLE_MODULE}.signal_loop_run_cancelled")
    def test_deactivation_cancels_a_transferred_loops_run_authored_by_the_user(
        self, mock_signal, _mock_dispatch, _mock_pause
    ):
        # The run's credentials come from its task's creator. If the loop was taken over after the
        # run started, it is no longer owned by the original author, so pausing loops by current
        # ownership misses the run — it would keep running under the deactivated author's credentials.
        new_owner = User.objects.create_user(email="new@example.com", first_name="New", password="password")
        loop = self._loop(created_by=new_owner)
        task = Task.objects.create(
            team=self.team,
            created_by=self.user,
            title="Active",
            description="d",
            origin_product=Task.OriginProduct.LOOP,
            internal=True,
        )
        run = task.create_run(mode="background", extra_state={"loop_id": str(loop.id)})
        run.status = TaskRun.Status.IN_PROGRESS
        run.save(update_fields=["status", "updated_at"])

        pause_loops_for_deactivated_user(self.user.id)

        run.refresh_from_db()
        self.assertEqual(run.status, TaskRun.Status.CANCELLED)
        mock_signal.assert_called_once_with(run.workflow_id)
