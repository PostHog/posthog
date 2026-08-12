import uuid

from unittest.mock import AsyncMock, MagicMock, patch

from django.test import TestCase

from parameterized import parameterized

from posthog.models import Organization, Team, User

from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.temporal.client import execute_task_processing_workflow, redispatch_orphaned_task_run

_PREFIX = "review-pr:1:posthog/posthog:67451/validate:validation-c3"


class TestWorkflowIdPrefix(TestCase):
    def setUp(self) -> None:
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create_user(email="wfid@example.com", first_name="Test", password="password")
        self.task = Task.objects.create(
            team=self.team,
            title="Test Task",
            description="Test Description",
            origin_product=Task.OriginProduct.USER_CREATED,
            created_by=self.user,
        )

    @parameterized.expand(
        [
            ("persisted_override", {"workflow_id": f"{_PREFIX}-t-r"}, f"{_PREFIX}-t-r"),
            ("no_override", {}, None),
            ("state_is_none", None, None),
        ]
    )
    def test_workflow_id_property_prefers_the_persisted_id(self, _name, state, expected) -> None:
        # A prefixed run's id is not derivable from (task_id, run_id); row→workflow lookups (the
        # heartbeat relay, follow-up signals, Temporal UI links) must read the persisted id or they
        # signal a nonexistent workflow. Default runs must keep the derived id (no persisted state).
        task_id, run_id = uuid.uuid4(), uuid.uuid4()
        run = TaskRun(task_id=task_id, id=run_id, state=state)
        assert run.workflow_id == (expected or f"task-processing-{task_id}-{run_id}")

    @parameterized.expand(
        [
            ("prefixed", _PREFIX),
            ("default", None),
        ]
    )
    def test_dispatch_starts_the_workflow_under_the_id_it_records(self, _name, prefix) -> None:
        # The id passed to Temporal and the id readable from the row must be the same value: using a
        # prefix without recording it (or recording without using it) strands the run for every
        # row→workflow lookup. A default dispatch must not write an override (parity with today).
        task_run = self.task.create_run(environment=TaskRun.Environment.CLOUD)
        temporal_client = MagicMock()
        temporal_client.start_workflow = AsyncMock()

        with patch("products.tasks.backend.temporal.client.sync_connect", return_value=temporal_client):
            execute_task_processing_workflow(
                task_id=str(self.task.id),
                run_id=str(task_run.id),
                team_id=self.team.id,
                user_id=self.user.id,
                workflow_id_prefix=prefix,
            )

        started_id = temporal_client.start_workflow.await_args.kwargs["id"]
        task_run.refresh_from_db()
        if prefix:
            assert started_id == f"{prefix}-{self.task.id}-{task_run.id}"
            assert task_run.state.get("workflow_id") == started_id
        else:
            assert started_id == f"task-processing-{self.task.id}-{task_run.id}"
            assert "workflow_id" not in (task_run.state or {})
        assert task_run.workflow_id == started_id

    def test_redispatch_recovers_the_prefix_from_pending_dispatch(self) -> None:
        # Crash window: the original dispatch can persist the prefixed id and die before starting the
        # workflow. A reconciler that then starts under the default id leaves the row pointing at a
        # workflow that never exists — the run wedges. It must rebuild the same prefixed id.
        task_run = self.task.create_run(
            environment=TaskRun.Environment.CLOUD,
            extra_state={"pending_dispatch": {"workflow_id_prefix": _PREFIX}},
        )
        task_run.status = TaskRun.Status.QUEUED
        task_run.save(update_fields=["status"])
        temporal_client = MagicMock()
        temporal_client.start_workflow = AsyncMock()

        with patch("products.tasks.backend.temporal.client.sync_connect", return_value=temporal_client):
            assert redispatch_orphaned_task_run(str(task_run.id)) == "recovered"

        started_id = temporal_client.start_workflow.await_args.kwargs["id"]
        task_run.refresh_from_db()
        assert started_id == f"{_PREFIX}-{self.task.id}-{task_run.id}"
        assert task_run.state.get("workflow_id") == started_id
