import uuid
import logging
import dataclasses
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from unittest import mock

from django.test import override_settings

from temporalio import activity
from temporalio.client import WorkflowFailureError, WorkflowHistory
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, UnsandboxedWorkflowRunner, Worker

from posthog.temporal.utils import ExternalDataWorkflowInputs

from products.warehouse_sources.backend.temporal.data_imports import external_data_job as workflow_module
from products.warehouse_sources.backend.temporal.data_imports.external_data_job import (
    CreateSourceTemplateInputs,
    ExternalDataJobWorkflow,
    UpdateExternalDataJobStatusInputs,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.typings import PipelineResult
from products.warehouse_sources.backend.temporal.data_imports.post_import_job import (
    PostImportContext,
    PostImportWorkflow,
    PostImportWorkflowInputs,
)
from products.warehouse_sources.backend.temporal.data_imports.settings import CONTROL_PLANE_ACTIVITIES
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.acquire_v3_lock import (
    AcquireV3LockActivityInputs,
    AcquireV3LockActivityOutputs,
)
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.check_billing_limits import (
    CheckBillingLimitsActivityInputs,
)
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.create_job_model import (
    CreateExternalDataJobModelActivityInputs,
    CreateExternalDataJobModelActivityOutputs,
)
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.import_data_sync import (
    ImportDataActivityInputs,
)

_IMPORT_QUEUE = "test-import-queue"
_CONTROL_PLANE_QUEUE = "test-control-plane-queue"
_JOB_ID = "01960000-0000-0000-0000-000000000001"

# What the import activity does in a scenario.
FAIL = "fail"
SUCCEED_WITH_WORKFLOW_FINALIZING = "succeed_with_workflow_finalizing"
HANDOFF = "handoff"

_CONTROL_PLANE_ACTIVITY_NAMES = {fn.__name__ for fn in CONTROL_PLANE_ACTIVITIES}


@pytest.fixture(autouse=True)
def _workflow_logs_at_info(caplog):
    caplog.set_level(logging.INFO, logger="temporalio.workflow")
    caplog.set_level(logging.INFO, logger="temporalio.activity")


@dataclasses.dataclass(frozen=True, kw_only=True)
class _Scenario:
    import_step: str
    billing_limit_checked: bool = True
    source_templates_needed: bool = False


def _recording_activities(scenario: _Scenario, calls: list[tuple[str, str]]) -> list:
    def record() -> None:
        info = activity.info()
        calls.append((info.activity_type, info.task_queue))

    @activity.defn(name="acquire_v3_pipeline_lock_activity")
    async def acquire_lock(inputs: AcquireV3LockActivityInputs) -> AcquireV3LockActivityOutputs:
        record()
        return AcquireV3LockActivityOutputs(acquired=True, token="token")

    @activity.defn(name="create_external_data_job_model_activity")
    async def create_job(inputs: CreateExternalDataJobModelActivityInputs) -> CreateExternalDataJobModelActivityOutputs:
        record()
        return CreateExternalDataJobModelActivityOutputs(
            job_id=_JOB_ID,
            incremental_or_append=False,
            source_type="Postgres",
            schema_name="orders",
            repartition_needed=False,
            billing_limit_checked=scenario.billing_limit_checked,
            source_templates_needed=scenario.source_templates_needed,
            import_handoffs_are_free=scenario.import_step == HANDOFF,
        )

    @activity.defn(name="check_billing_limits_activity")
    async def check_billing(inputs: CheckBillingLimitsActivityInputs) -> bool:
        record()
        return False

    @activity.defn(name="import_data_activity_sync")
    async def import_data(inputs: ImportDataActivityInputs) -> PipelineResult:
        record()
        if scenario.import_step == FAIL:
            raise ApplicationError("source went away", non_retryable=True)
        if scenario.import_step == HANDOFF:
            return PipelineResult(should_trigger_cdp_producer=False, handed_off=True, handoff_attempts_used=1)
        return PipelineResult(should_trigger_cdp_producer=False, consumer_manages_job_status=False)

    @activity.defn(name="create_source_templates")
    async def create_templates(inputs: CreateSourceTemplateInputs) -> None:
        record()

    @activity.defn(name="update_external_data_job_model")
    async def update_job(inputs: UpdateExternalDataJobStatusInputs) -> None:
        record()

    @activity.defn(name="trigger_schedule_buffer_one_activity")
    async def trigger_buffer_one(schedule_id: str) -> None:
        record()

    @activity.defn(name="resolve_post_import_context_activity")
    async def resolve_post_import(inputs: PostImportWorkflowInputs) -> PostImportContext:
        record()
        return PostImportContext(steps=[])

    return [
        acquire_lock,
        create_job,
        check_billing,
        import_data,
        create_templates,
        update_job,
        trigger_buffer_one,
        resolve_post_import,
    ]


def _routing_settings(enabled: bool) -> Any:
    return override_settings(
        DATA_WAREHOUSE_CONTROL_PLANE_ROUTING_ENABLED=enabled,
        DATA_WAREHOUSE_CONTROL_PLANE_TASK_QUEUE=_CONTROL_PLANE_QUEUE,
    )


async def _run(
    workflow_run: Any, workflow_input: Any, scenario: _Scenario
) -> tuple[list[tuple[str, str]], WorkflowHistory]:
    calls: list[tuple[str, str]] = []
    activities = _recording_activities(scenario, calls)
    with (
        mock.patch.object(workflow_module.workflow, "start_child_workflow", new_callable=mock.AsyncMock),
        mock.patch.object(workflow_module, "get_data_import_finished_metric"),
        mock.patch.object(workflow_module, "get_import_handoffs_per_run_metric"),
        mock.patch.object(workflow_module, "MAX_IMPORT_HANDOFFS", 1),
    ):
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with (
                Worker(
                    env.client,
                    task_queue=_IMPORT_QUEUE,
                    workflows=[ExternalDataJobWorkflow, PostImportWorkflow],
                    activities=activities,
                    workflow_runner=UnsandboxedWorkflowRunner(),
                    activity_executor=ThreadPoolExecutor(max_workers=4),
                ),
                Worker(
                    env.client,
                    task_queue=_CONTROL_PLANE_QUEUE,
                    activities=activities,
                    activity_executor=ThreadPoolExecutor(max_workers=4),
                ),
            ):
                handle = await env.client.start_workflow(
                    workflow_run,
                    workflow_input,
                    id=str(uuid.uuid4()),
                    task_queue=_IMPORT_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                    execution_timeout=workflow_module.dt.timedelta(hours=1),
                )
                try:
                    await handle.result()
                except WorkflowFailureError:
                    pass
                history = await handle.fetch_history()
    return calls, history


def _import_run() -> tuple[Any, Any]:
    return (
        ExternalDataJobWorkflow.run,
        ExternalDataWorkflowInputs(
            team_id=1,
            external_data_source_id=uuid.uuid4(),
            external_data_schema_id=uuid.uuid4(),
            billable=False,
        ),
    )


def _post_import_run() -> tuple[Any, Any]:
    return (
        PostImportWorkflow.run,
        PostImportWorkflowInputs(team_id=1, job_id=_JOB_ID, schema_id=str(uuid.uuid4()), source_id=str(uuid.uuid4())),
    )


_SCENARIOS = [
    pytest.param(
        _import_run,
        _Scenario(import_step=FAIL),
        [
            "acquire_v3_pipeline_lock_activity",
            "create_external_data_job_model_activity",
            "import_data_activity_sync",
            "update_external_data_job_model",
        ],
        id="failed_import",
    ),
    pytest.param(
        _import_run,
        _Scenario(
            import_step=SUCCEED_WITH_WORKFLOW_FINALIZING, billing_limit_checked=False, source_templates_needed=True
        ),
        [
            "acquire_v3_pipeline_lock_activity",
            "create_external_data_job_model_activity",
            "check_billing_limits_activity",
            "import_data_activity_sync",
            "create_source_templates",
            "update_external_data_job_model",
        ],
        id="completed_import_with_legacy_billing_check_and_templates",
    ),
    pytest.param(
        _import_run,
        _Scenario(import_step=HANDOFF),
        [
            "acquire_v3_pipeline_lock_activity",
            "create_external_data_job_model_activity",
            "import_data_activity_sync",
            "trigger_schedule_buffer_one_activity",
            "update_external_data_job_model",
        ],
        id="handoff_bound_reached",
    ),
    pytest.param(
        _post_import_run,
        _Scenario(import_step=SUCCEED_WITH_WORKFLOW_FINALIZING),
        ["resolve_post_import_context_activity"],
        id="post_import",
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("routing_enabled", [False, True], ids=["routing_off", "routing_on"])
@pytest.mark.parametrize("make_run,scenario,expected_activities", _SCENARIOS)
async def test_each_activity_runs_on_its_queue(
    routing_enabled: bool, make_run: Any, scenario: _Scenario, expected_activities: list[str]
) -> None:
    workflow_run, workflow_input = make_run()
    with _routing_settings(routing_enabled):
        calls, _ = await _run(workflow_run, workflow_input, scenario)

    assert [name for name, _ in calls] == expected_activities
    for name, task_queue in calls:
        routed = routing_enabled and name in _CONTROL_PLANE_ACTIVITY_NAMES
        # An activity routed but missing from CONTROL_PLANE_ACTIVITIES has no poller in production.
        assert task_queue == (_CONTROL_PLANE_QUEUE if routed else _IMPORT_QUEUE), name


@pytest.mark.asyncio
@pytest.mark.parametrize("recorded_with_routing", [False, True], ids=["recorded_off", "recorded_on"])
@pytest.mark.parametrize(
    "make_run,scenario",
    [
        pytest.param(
            _import_run,
            _Scenario(
                import_step=SUCCEED_WITH_WORKFLOW_FINALIZING, billing_limit_checked=False, source_templates_needed=True
            ),
            id="import",
        ),
        pytest.param(_post_import_run, _Scenario(import_step=SUCCEED_WITH_WORKFLOW_FINALIZING), id="post_import"),
    ],
)
async def test_a_history_replays_after_the_routing_setting_changes(
    recorded_with_routing: bool, make_run: Any, scenario: _Scenario
) -> None:
    workflow_run, workflow_input = make_run()
    with _routing_settings(recorded_with_routing):
        _, history = await _run(workflow_run, workflow_input, scenario)

    with (
        _routing_settings(not recorded_with_routing),
        mock.patch.object(workflow_module, "get_data_import_finished_metric"),
        mock.patch.object(workflow_module, "get_import_handoffs_per_run_metric"),
        mock.patch.object(workflow_module, "MAX_IMPORT_HANDOFFS", 1),
        mock.patch.object(workflow_module.workflow, "start_child_workflow", new_callable=mock.AsyncMock),
    ):
        await Replayer(
            workflows=[ExternalDataJobWorkflow, PostImportWorkflow],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ).replay_workflow(history)
