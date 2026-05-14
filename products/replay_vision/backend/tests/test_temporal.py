import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from unittest.mock import patch

from django.db import IntegrityError
from django.utils import timezone

import psycopg.errors
import pytest_asyncio
from asgiref.sync import sync_to_async
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.models import Organization, Team
from posthog.models.user import User

from products.replay_vision.backend.models.replay_lens import LensModel, LensType, ReplayLens
from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ObservationTrigger,
    ReplayObservation,
)
from products.replay_vision.backend.temporal import ACTIVITIES, ApplyLensWorkflow
from products.replay_vision.backend.temporal.activities.create_observation import create_observation_activity
from products.replay_vision.backend.temporal.activities.observation_state import (
    mark_observation_failed_activity,
    mark_observation_running_activity,
)
from products.replay_vision.backend.temporal.constants import build_apply_lens_workflow_id
from products.replay_vision.backend.temporal.types import (
    ApplyLensInputs,
    CreateObservationInputs,
    CreateObservationOutput,
    MarkObservationFailedInputs,
    MarkObservationRunningInputs,
)


def _make_lens() -> ReplayLens:
    org = Organization.objects.create(name="vision-test-org")
    team = Team.objects.create(organization=org, name="vision-test-team")
    return ReplayLens.objects.create(
        team=team,
        name="t",
        lens_type=LensType.MONITOR,
        lens_config={"prompt": "p"},
        model=LensModel.GEMINI_3_FLASH,
    )


def _make_observation(lens: ReplayLens, **overrides) -> ReplayObservation:
    defaults: dict = {
        "lens": lens,
        "team": lens.team,
        "session_id": "sess-1",
        "triggered_by": ObservationTrigger.ON_DEMAND,
        "lens_version": lens.lens_version,
        "lens_config_snapshot": lens.lens_config,
    }
    defaults.update(overrides)
    return ReplayObservation.objects.create(**defaults)


@pytest_asyncio.fixture(scope="module")
async def workflow_env() -> AsyncIterator[WorkflowEnvironment]:
    async with await WorkflowEnvironment.start_time_skipping() as env:
        yield env


@pytest.fixture(scope="module")
def thread_pool_executor() -> Iterator[ThreadPoolExecutor]:
    with ThreadPoolExecutor(max_workers=4) as executor:
        yield executor


@pytest.mark.django_db(transaction=True)
class TestCreateObservationActivity:
    def test_creates_row_in_pending_with_workflow_id_and_snapshot(self) -> None:
        lens = _make_lens()
        result = create_observation_activity(
            CreateObservationInputs(
                lens_id=lens.id,
                team_id=lens.team_id,
                session_id="sess-1",
                triggered_by=ObservationTrigger.ON_DEMAND,
                triggered_by_user_id=None,
                workflow_id="wf-xyz",
            )
        )

        assert result.was_created is True
        observation = ReplayObservation.objects.get(id=result.observation_id)
        assert observation.status == ObservationStatus.PENDING
        assert observation.workflow_id == "wf-xyz"
        assert observation.session_id == "sess-1"
        assert observation.triggered_by == ObservationTrigger.ON_DEMAND
        assert observation.lens_version == lens.lens_version
        assert observation.lens_config_snapshot == lens.lens_config
        assert observation.started_at is None  # set when transitioning to running, not here
        assert observation.completed_at is None

    def test_snapshot_is_frozen_against_later_lens_edits(self) -> None:
        lens = _make_lens()
        original_config = dict(lens.lens_config)
        result = create_observation_activity(
            CreateObservationInputs(
                lens_id=lens.id,
                team_id=lens.team_id,
                session_id="sess-1",
                triggered_by=ObservationTrigger.SCHEDULE,
                triggered_by_user_id=None,
                workflow_id="wf-1",
            )
        )

        lens.lens_config = {"prompt": "completely different prompt"}
        lens.save()

        observation = ReplayObservation.objects.get(id=result.observation_id)
        assert observation.lens_config_snapshot == original_config

    def test_returns_existing_observation_on_unique_conflict(self) -> None:
        lens = _make_lens()
        existing = _make_observation(lens, session_id="sess-dup")

        result = create_observation_activity(
            CreateObservationInputs(
                lens_id=lens.id,
                team_id=lens.team_id,
                session_id="sess-dup",
                triggered_by=ObservationTrigger.ON_DEMAND,
                triggered_by_user_id=None,
                workflow_id="wf-second",
            )
        )

        assert result == CreateObservationOutput(observation_id=existing.id, was_created=False)
        # The original row wasn't touched.
        existing.refresh_from_db()
        assert existing.workflow_id != "wf-second"

    def test_propagates_non_unique_integrity_errors(self) -> None:
        # FK/CHECK violations must surface as activity failures, not silently fall into the dedup path.
        lens = _make_lens()
        fk_error = IntegrityError("insert or update on table violates foreign key constraint")
        fk_error.__cause__ = psycopg.errors.ForeignKeyViolation("violation")

        with patch.object(ReplayObservation.objects, "create", side_effect=fk_error):
            with pytest.raises(IntegrityError):
                create_observation_activity(
                    CreateObservationInputs(
                        lens_id=lens.id,
                        team_id=lens.team_id,
                        session_id="sess-fk",
                        triggered_by=ObservationTrigger.ON_DEMAND,
                        triggered_by_user_id=None,
                        workflow_id="wf-fk",
                    )
                )

        assert not ReplayObservation.objects.filter(lens=lens, session_id="sess-fk").exists()

    @pytest.mark.parametrize(
        "use_real_lens_id, team_id_offset",
        [
            pytest.param(False, 0, id="lens_does_not_exist"),
            pytest.param(True, 999, id="lens_belongs_to_other_team"),
        ],
    )
    def test_raises_when_lens_not_found_for_team(self, use_real_lens_id: bool, team_id_offset: int) -> None:
        lens = _make_lens()
        lens_id = lens.id if use_real_lens_id else uuid.uuid4()
        team_id = lens.team_id + team_id_offset

        with pytest.raises(ValueError):
            create_observation_activity(
                CreateObservationInputs(
                    lens_id=lens_id,
                    team_id=team_id,
                    session_id="sess-1",
                    triggered_by=ObservationTrigger.ON_DEMAND,
                    triggered_by_user_id=None,
                    workflow_id="wf-1",
                )
            )

    def test_raises_when_user_is_not_in_lens_organization(self) -> None:
        lens = _make_lens()
        outsider_org = Organization.objects.create(name="other-org")
        outsider = User.objects.create_and_join(organization=outsider_org, email="x@x.com", password=None)

        with pytest.raises(ValueError, match="not a member"):
            create_observation_activity(
                CreateObservationInputs(
                    lens_id=lens.id,
                    team_id=lens.team_id,
                    session_id="sess-1",
                    triggered_by=ObservationTrigger.ON_DEMAND,
                    triggered_by_user_id=outsider.id,
                    workflow_id="wf-1",
                )
            )

    def test_accepts_user_in_lens_organization(self) -> None:
        lens = _make_lens()
        member = User.objects.create_and_join(organization=lens.team.organization, email="m@m.com", password=None)

        result = create_observation_activity(
            CreateObservationInputs(
                lens_id=lens.id,
                team_id=lens.team_id,
                session_id="sess-1",
                triggered_by=ObservationTrigger.ON_DEMAND,
                triggered_by_user_id=member.id,
                workflow_id="wf-1",
            )
        )
        assert result.was_created is True


@pytest.mark.django_db(transaction=True)
class TestObservationStateActivities:
    def test_mark_running_stamps_started_at(self) -> None:
        lens = _make_lens()
        observation = _make_observation(lens, workflow_id="wf-1")
        assert observation.status == ObservationStatus.PENDING

        mark_observation_running_activity(MarkObservationRunningInputs(observation_id=observation.id))

        observation.refresh_from_db()
        assert observation.status == ObservationStatus.RUNNING
        assert observation.workflow_id == "wf-1"
        assert observation.started_at is not None

    def test_mark_failed_records_reason_and_completed_at(self) -> None:
        lens = _make_lens()
        observation = _make_observation(lens)
        observation.status = ObservationStatus.RUNNING
        observation.started_at = timezone.now()
        observation.save(update_fields=["status", "started_at"])

        mark_observation_failed_activity(
            MarkObservationFailedInputs(observation_id=observation.id, error_reason="bad output")
        )

        observation.refresh_from_db()
        assert observation.status == ObservationStatus.FAILED
        assert observation.error_reason == "bad output"
        assert observation.completed_at is not None

    @pytest.mark.parametrize("terminal_status", [ObservationStatus.SUCCEEDED, ObservationStatus.FAILED])
    def test_terminal_status_is_not_overwritten_by_state_activities(self, terminal_status: str) -> None:
        # Bounded UPDATE protects against retries that race past a settled row.
        lens = _make_lens()
        observation = _make_observation(lens)
        observation.status = terminal_status
        observation.completed_at = timezone.now()
        observation.error_reason = "original"
        observation.save(update_fields=["status", "completed_at", "error_reason"])

        mark_observation_running_activity(MarkObservationRunningInputs(observation_id=observation.id))
        mark_observation_failed_activity(
            MarkObservationFailedInputs(observation_id=observation.id, error_reason="late failure")
        )

        observation.refresh_from_db()
        assert observation.status == terminal_status
        assert observation.error_reason == "original"

    def test_mark_running_is_idempotent_against_already_running_rows(self) -> None:
        # `started_at` must survive at-least-once retries; duration metrics depend on it.
        lens = _make_lens()
        observation = _make_observation(lens)
        mark_observation_running_activity(MarkObservationRunningInputs(observation_id=observation.id))
        observation.refresh_from_db()
        first_started_at = observation.started_at
        assert first_started_at is not None

        mark_observation_running_activity(MarkObservationRunningInputs(observation_id=observation.id))
        observation.refresh_from_db()
        assert observation.started_at == first_started_at


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_apply_lens_workflow_creates_row_then_marks_failed_with_stub_reason(
    workflow_env: WorkflowEnvironment, thread_pool_executor: ThreadPoolExecutor
) -> None:
    lens = await sync_to_async(_make_lens)()
    workflow_id = build_apply_lens_workflow_id(lens.id, "sess-1")
    task_queue = f"vision-test-{uuid.uuid4()}"

    async with Worker(
        workflow_env.client,
        task_queue=task_queue,
        workflows=[ApplyLensWorkflow],
        activities=ACTIVITIES,
        activity_executor=thread_pool_executor,
        workflow_runner=UnsandboxedWorkflowRunner(),
    ):
        await workflow_env.client.execute_workflow(
            ApplyLensWorkflow.run,
            ApplyLensInputs(
                lens_id=lens.id,
                session_id="sess-1",
                team_id=lens.team_id,
                triggered_by=ObservationTrigger.ON_DEMAND,
                triggered_by_user_id=None,
            ),
            id=workflow_id,
            task_queue=task_queue,
        )

    @sync_to_async
    def _reload() -> ReplayObservation:
        return ReplayObservation.objects.get(lens=lens, session_id="sess-1")

    final = await _reload()
    assert final.status == ObservationStatus.FAILED
    assert "stub" in final.error_reason.lower()
    assert final.workflow_id == workflow_id
    assert final.started_at is not None
    assert final.completed_at is not None


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_apply_lens_workflow_no_ops_when_observation_already_exists(
    workflow_env: WorkflowEnvironment, thread_pool_executor: ThreadPoolExecutor
) -> None:
    lens = await sync_to_async(_make_lens)()
    existing = await sync_to_async(_make_observation)(
        lens,
        session_id="sess-dup",
        workflow_id="prior-workflow",
        status=ObservationStatus.SUCCEEDED,
        completed_at=timezone.now(),
    )

    workflow_id = build_apply_lens_workflow_id(lens.id, "sess-dup")
    task_queue = f"vision-test-{uuid.uuid4()}"

    async with Worker(
        workflow_env.client,
        task_queue=task_queue,
        workflows=[ApplyLensWorkflow],
        activities=ACTIVITIES,
        activity_executor=thread_pool_executor,
        workflow_runner=UnsandboxedWorkflowRunner(),
    ):
        await workflow_env.client.execute_workflow(
            ApplyLensWorkflow.run,
            ApplyLensInputs(
                lens_id=lens.id,
                session_id="sess-dup",
                team_id=lens.team_id,
                triggered_by=ObservationTrigger.ON_DEMAND,
                triggered_by_user_id=None,
            ),
            id=workflow_id,
            task_queue=task_queue,
        )

    # Existing row stays exactly as it was — no new rows created.
    @sync_to_async
    def _check() -> tuple[int, ReplayObservation]:
        rows = ReplayObservation.objects.filter(lens=lens, session_id="sess-dup")
        return rows.count(), rows.get()

    count, observation = await _check()
    assert count == 1
    assert observation.id == existing.id
    assert observation.workflow_id == "prior-workflow"
    assert observation.status == ObservationStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_apply_lens_workflow_orchestrates_activities_in_order(workflow_env: WorkflowEnvironment) -> None:
    calls: list[tuple[str, dict]] = []
    new_observation_id = uuid.uuid4()

    @activity.defn(name="create_observation_activity")
    async def stub_create(inputs: CreateObservationInputs) -> CreateObservationOutput:
        calls.append(
            (
                "create",
                {
                    "lens_id": inputs.lens_id,
                    "session_id": inputs.session_id,
                    "triggered_by": inputs.triggered_by,
                    "workflow_id": inputs.workflow_id,
                },
            )
        )
        return CreateObservationOutput(observation_id=new_observation_id, was_created=True)

    @activity.defn(name="mark_observation_running_activity")
    async def stub_running(inputs: MarkObservationRunningInputs) -> None:
        calls.append(("running", {"observation_id": inputs.observation_id}))

    @activity.defn(name="mark_observation_failed_activity")
    async def stub_failed(inputs: MarkObservationFailedInputs) -> None:
        calls.append(("failed", {"observation_id": inputs.observation_id, "error_reason": inputs.error_reason}))

    lens_id = uuid.uuid4()
    workflow_id = build_apply_lens_workflow_id(lens_id, "sess-x")
    task_queue = f"vision-test-{uuid.uuid4()}"
    activities: list[Callable[..., Any]] = [stub_create, stub_running, stub_failed]

    async with Worker(
        workflow_env.client,
        task_queue=task_queue,
        workflows=[ApplyLensWorkflow],
        activities=activities,
        workflow_runner=UnsandboxedWorkflowRunner(),
    ):
        await workflow_env.client.execute_workflow(
            ApplyLensWorkflow.run,
            ApplyLensInputs(
                lens_id=lens_id,
                session_id="sess-x",
                team_id=1,
                triggered_by=ObservationTrigger.SCHEDULE,
                triggered_by_user_id=None,
            ),
            id=workflow_id,
            task_queue=task_queue,
        )

    assert [name for name, _ in calls] == ["create", "running", "failed"]
    assert calls[0][1] == {
        "lens_id": lens_id,
        "session_id": "sess-x",
        "triggered_by": ObservationTrigger.SCHEDULE,
        "workflow_id": workflow_id,
    }
    assert calls[1][1] == {"observation_id": new_observation_id}
    assert calls[2][1]["observation_id"] == new_observation_id
    assert "stub" in calls[2][1]["error_reason"].lower()


@pytest.mark.asyncio
async def test_apply_lens_workflow_exits_when_create_returns_was_created_false(
    workflow_env: WorkflowEnvironment,
) -> None:
    calls: list[str] = []

    @activity.defn(name="create_observation_activity")
    async def stub_create(inputs: CreateObservationInputs) -> CreateObservationOutput:
        calls.append("create")
        return CreateObservationOutput(observation_id=uuid.uuid4(), was_created=False)

    @activity.defn(name="mark_observation_running_activity")
    async def stub_running(inputs: MarkObservationRunningInputs) -> None:
        calls.append("running")

    @activity.defn(name="mark_observation_failed_activity")
    async def stub_failed(inputs: MarkObservationFailedInputs) -> None:
        calls.append("failed")

    activities: list[Callable[..., Any]] = [stub_create, stub_running, stub_failed]
    task_queue = f"vision-test-{uuid.uuid4()}"

    async with Worker(
        workflow_env.client,
        task_queue=task_queue,
        workflows=[ApplyLensWorkflow],
        activities=activities,
        workflow_runner=UnsandboxedWorkflowRunner(),
    ):
        await workflow_env.client.execute_workflow(
            ApplyLensWorkflow.run,
            ApplyLensInputs(
                lens_id=uuid.uuid4(),
                session_id="sess-y",
                team_id=1,
                triggered_by=ObservationTrigger.ON_DEMAND,
                triggered_by_user_id=None,
            ),
            id="wf-y",
            task_queue=task_queue,
        )

    assert calls == ["create"]
