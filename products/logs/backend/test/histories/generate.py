"""Record LogsAlertCheckWorkflow histories for test_logs_alerting_replay.py.

Run from the repo root through the Django shell so activity imports have initialized apps.
Test mode skips startup services because recording uses fake activities:

    TEST=1 python manage.py shell -c "from products.logs.backend.test.histories.generate import main; main('bounded_cap_2')"
    TEST=1 python manage.py shell -c "from products.logs.backend.test.histories.generate import main; main('unbounded_before_patch', 'path/to/old_workflow.py')"

`unbounded_before_patch` must be recorded with the workflow code from before
`logs-alerting-bounded-batch-fanout`, for example `git show <sha>:products/logs/backend/temporal/workflow.py`.
"""

import json
import uuid
import asyncio
import dataclasses
import importlib.util
from pathlib import Path

from temporalio import activity
from temporalio.client import WorkflowHistory
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.logs.backend.temporal.activities import (
    CheckAlertsInput,
    CohortManifest,
    DiscoverCohortsInput,
    EvaluateCohortBatchInput,
    EvaluateCohortBatchOutput,
)
from products.logs.backend.temporal.constants import WORKFLOW_NAME
from products.logs.backend.temporal.workflow import LogsAlertCheckWorkflow

MANIFESTS = [
    CohortManifest(
        team_id=1,
        projection_eligible=True,
        date_to_iso="2026-10-01T10:05:00+00:00",
        alert_ids=[f"alert-{i}"],
    )
    for i in range(7)
]


@dataclasses.dataclass(frozen=True)
class _DiscoveryBeforeCap:
    manifests: list[CohortManifest]
    batch_size: int


@dataclasses.dataclass(frozen=True)
class _DiscoveryWithCap:
    manifests: list[CohortManifest]
    batch_size: int
    max_concurrent_batches: int


@activity.defn(name="evaluate_cohort_batch_activity")
async def _evaluate(input: EvaluateCohortBatchInput) -> EvaluateCohortBatchOutput:
    return EvaluateCohortBatchOutput(
        alerts_checked=len(input.manifests), alerts_fired=0, alerts_resolved=0, alerts_errored=0
    )


async def _record(workflow_cls: type, discovery: object) -> WorkflowHistory:
    @activity.defn(name="discover_cohorts_activity")
    async def _discover(_input: DiscoverCohortsInput) -> object:
        return discovery

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue="logs-alerting-replay",
            workflows=[workflow_cls],
            activities=[_discover, _evaluate],
            workflow_runner=UnsandboxedWorkflowRunner(),
            identity="replay-test-worker",
        ):
            handle = await env.client.start_workflow(
                WORKFLOW_NAME,
                CheckAlertsInput(),
                id=f"logs-alert-check-replay-{uuid.uuid4()}",
                task_queue="logs-alerting-replay",
            )
            await handle.result()
            return await handle.fetch_history()


def _write(name: str, history: WorkflowHistory) -> None:
    # The client and worker record "pid@hostname" as their identity. Replay ignores it,
    # so a fixed value keeps the machine that recorded the fixture out of the repo.
    events = json.loads(history.to_json())
    _normalize_identity(events)
    (Path(__file__).parent / f"{name}.json").write_text(json.dumps(events, indent=4) + "\n")


def _normalize_identity(node: object) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "identity":
                node[key] = "replay-test-worker"
            else:
                _normalize_identity(value)
    elif isinstance(node, list):
        for item in node:
            _normalize_identity(item)


def main(name: str, old_workflow_path: str | None = None) -> None:
    if name == "unbounded_before_patch":
        if old_workflow_path is None:
            raise ValueError("Provide the pre-patch workflow file path to record unbounded_before_patch")
        spec = importlib.util.spec_from_file_location("old_workflow", old_workflow_path)
        assert spec and spec.loader
        old = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(old)
        _write(name, asyncio.run(_record(old.LogsAlertCheckWorkflow, _DiscoveryBeforeCap(MANIFESTS, 3))))
    elif name == "bounded_cap_2":
        _write(name, asyncio.run(_record(LogsAlertCheckWorkflow, _DiscoveryWithCap(MANIFESTS, 3, 2))))
    else:
        raise SystemExit(f"unknown history {name}")
