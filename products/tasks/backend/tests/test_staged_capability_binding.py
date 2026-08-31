from uuid import uuid4

from django.test import TestCase

from posthog.models import Organization, Team, User

from products.tasks.backend.facade import api as tasks_api
from products.tasks.backend.models import Task, TaskRun, TaskStagedRunTransition


class TestStagedTaskCapabilityBinding(TestCase):
    def setUp(self) -> None:
        organization = Organization.objects.create(name="Staged capability org")
        self.team = Team.objects.create(organization=organization, name="Staged capability team")
        self.user = User.objects.create(email="staged-capability@example.com")
        self.caller_id = uuid4()
        self.task = Task.objects.create(
            team=self.team,
            created_by=self.user,
            title="Pulse execution",
            description="Create one reserved artifact.",
            origin_product=Task.OriginProduct.WORKFLOW,
            origin_key="pulse-execution-1",
            internal=True,
            state={
                "staged_caller_id": str(self.caller_id),
                "staged_idempotency_key": "pulse-execution-1",
            },
        )
        self.source_run = TaskRun.objects.create(
            task=self.task,
            team=self.team,
            status=TaskRun.Status.COMPLETED,
            state={"snapshot_external_id": "snapshot-1"},
        )
        self.successor_run = TaskRun.objects.create(
            task=self.task,
            team=self.team,
            status=TaskRun.Status.IN_PROGRESS,
            state={},
        )
        self.manifest = {
            "version": 1,
            "phase": "execution",
            "capabilities": ["read", "experiment_draft"],
            "bindings": {
                "caller_id": str(self.caller_id),
                "task_id": str(self.task.id),
                "run_id": str(self.successor_run.id),
                "publication_allowed": False,
            },
        }
        self.transition = TaskStagedRunTransition.objects.for_team(self.team.id).create(
            team=self.team,
            caller_id=self.caller_id,
            task=self.task,
            source_task_run=self.source_run,
            successor_task_run=self.successor_run,
            source_workspace_snapshot_ref="snapshot-1",
            requested_capability_manifest=self.manifest,
            status=TaskStagedRunTransition.Status.ADVANCED,
            idempotency_key="pulse-transition-1",
        )
        self.successor_run.state = {
            "staged_phase": "execution",
            "staged_transition_id": str(self.transition.id),
            "staged_manifest": self.manifest,
        }
        self.successor_run.save(update_fields=["state"])

    def test_resolves_server_owned_live_binding(self) -> None:
        binding = tasks_api.resolve_staged_task_capability_binding(
            team_id=self.team.id,
            task_id=self.task.id,
            required_capability="experiment_draft",
        )

        assert binding is not None
        assert binding.team_id == self.team.id
        assert binding.task_id == self.task.id
        assert binding.task_run_id == self.successor_run.id
        assert binding.caller_id == self.caller_id
        assert binding.actor_id == self.user.id

    def test_denies_missing_capability_and_terminal_run(self) -> None:
        assert (
            tasks_api.resolve_staged_task_capability_binding(
                team_id=self.team.id,
                task_id=self.task.id,
                required_capability="draft",
            )
            is None
        )

        self.successor_run.status = TaskRun.Status.CANCELLED
        self.successor_run.save(update_fields=["status"])

        assert (
            tasks_api.resolve_staged_task_capability_binding(
                team_id=self.team.id,
                task_id=self.task.id,
                required_capability="experiment_draft",
            )
            is None
        )

    def test_denies_manifest_or_identity_tampering(self) -> None:
        state = dict(self.successor_run.state)
        manifest = dict(state["staged_manifest"])
        manifest["bindings"] = {**manifest["bindings"], "caller_id": str(uuid4())}
        state["staged_manifest"] = manifest
        self.successor_run.state = state
        self.successor_run.save(update_fields=["state"])

        assert (
            tasks_api.resolve_staged_task_capability_binding(
                team_id=self.team.id,
                task_id=self.task.id,
                required_capability="experiment_draft",
            )
            is None
        )
