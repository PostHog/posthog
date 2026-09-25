from __future__ import annotations

import json
import asyncio
import hashlib
from datetime import timedelta
from typing import Literal, cast
from uuid import UUID

from django.utils import timezone

from asgiref.sync import async_to_sync
from pydantic import JsonValue, TypeAdapter
from temporalio.client import WorkflowExecutionStatus, WorkflowFailureError
from temporalio.service import RPCError, RPCStatusCode

from posthog.dataclasses import frozen
from posthog.storage import object_storage
from posthog.temporal.common.client import async_connect

from products.signals.backend.models import SignalScoutRun
from products.signals.backend.scout_harness.trial_launch import TrialLaunch, read_trial_launch
from products.signals.backend.scout_harness.trial_state import SCOUT_TRIAL_METADATA_KEY, ScoutTrialStore

MAX_TRIAL_RESULT_BYTES = 4 * 1024 * 1024
_RUNTIME_FIELDS = ("runtime_adapter", "model", "reasoning_effort", "service_tier")


@frozen
class TrialWorkflowStatus:
    status: Literal["pending", "completed", "skipped", "failed", "cancelled", "not_started", "unknown"]
    error: str | None = None
    run_id: str | None = None


@async_to_sync
async def get_trial_workflow_status(*, team_id: int, launch_id: UUID) -> TrialWorkflowStatus:
    from products.signals.backend.temporal.agentic.scout_scheduler import (  # noqa: PLC0415 -- the scout runner imports result exports
        RunSignalsScoutOutput,
        trial_run_workflow_id,
    )

    try:
        async with asyncio.timeout(5):
            client = await async_connect()
            handle = client.get_workflow_handle(
                trial_run_workflow_id(team_id, str(launch_id)), result_type=RunSignalsScoutOutput
            )
            description = await handle.describe(rpc_timeout=timedelta(seconds=5))
            match description.status:
                case WorkflowExecutionStatus.RUNNING | WorkflowExecutionStatus.CONTINUED_AS_NEW:
                    return TrialWorkflowStatus(status="pending")
                case WorkflowExecutionStatus.COMPLETED:
                    output = await handle.result(rpc_timeout=timedelta(seconds=5))
                    if output.skip_reason:
                        return TrialWorkflowStatus(
                            status="skipped",
                            error=f"The scout did not start: {output.skip_reason}. Check the launch settings before retrying.",
                            run_id=output.run_id,
                        )
                    if output.status in {"completed", "failed", "cancelled"}:
                        return TrialWorkflowStatus(
                            status=cast(Literal["completed", "failed", "cancelled"], output.status),
                            error=None
                            if output.status == "completed"
                            else "The scout stopped before completion. Check the trial logs before starting another run.",
                            run_id=output.run_id,
                        )
                    return TrialWorkflowStatus(
                        status="failed",
                        error="The scout worker finished without a completed run. Check whether its sandbox is still running.",
                        run_id=output.run_id,
                    )
                case WorkflowExecutionStatus.CANCELED | WorkflowExecutionStatus.TERMINATED:
                    return TrialWorkflowStatus(
                        status="cancelled",
                        error="The scout worker was canceled. Check whether its sandbox is still running.",
                    )
                case WorkflowExecutionStatus.TIMED_OUT:
                    return TrialWorkflowStatus(
                        status="failed",
                        error="The scout worker timed out. Check whether its sandbox is still running.",
                    )
                case WorkflowExecutionStatus.FAILED:
                    return TrialWorkflowStatus(
                        status="failed",
                        error="The scout worker failed. Check the trial logs before starting another run.",
                    )
    except RPCError as error:
        if error.status == RPCStatusCode.NOT_FOUND:
            return TrialWorkflowStatus(
                status="not_started", error="The scout trial has not started. Retry the launch with the same ID."
            )
    except WorkflowFailureError:
        return TrialWorkflowStatus(
            status="failed", error="The scout worker failed. Check the trial logs before starting another run."
        )
    except (TimeoutError, RuntimeError):
        pass
    return TrialWorkflowStatus(status="unknown", error="The scout status is unavailable. Try this request again.")


def validate_trial_runtime(run: SignalScoutRun, launch: TrialLaunch) -> str | None:
    run.task_run.refresh_from_db(fields=["state", "status"])
    state = run.task_run.state or {}
    store = ScoutTrialStore(run)
    if any(state.get(field) != getattr(launch, field) for field in _RUNTIME_FIELDS):
        store.invalidate("The task's model, effort, or runtime changed during the scout trial.", allow_terminal=True)
    return store.invalid_reason()


def trial_result_key(run: SignalScoutRun) -> str:
    return f"signals/scout-trials/{run.team_id}/results/{run.id}.json"


def read_trial_result(run: SignalScoutRun) -> dict[str, JsonValue] | None:
    content = object_storage.read(trial_result_key(run), missing_ok=True)
    if content is None:
        return None
    result = TypeAdapter(dict[str, JsonValue]).validate_json(content)
    if (
        result.get("version") != 1
        or result.get("run_id") != str(run.id)
        or result.get("task_run_id") != str(run.task_run_id)
        or result.get("status") not in ("completed", "failed", "cancelled")
    ):
        raise ValueError("The saved result does not match this scout trial.")
    return result


def export_trial_result(run: SignalScoutRun, *, status: str | None = None) -> str:
    key = trial_result_key(run)
    if status is None and read_trial_result(run) is not None:
        return key
    marker = (run.metadata or {})[SCOUT_TRIAL_METADATA_KEY]
    launch = read_trial_launch(run.team_id, marker["launch_id"])
    invalid_reason = validate_trial_runtime(run, launch)
    state = run.task_run.state or {}
    result: dict[str, JsonValue] = {
        "version": 1,
        "run_id": str(run.id),
        "task_run_id": str(run.task_run_id),
        "launch_id": str(launch.id),
        "context_id": str(launch.context_id),
        "created_at": run.created_at.isoformat(),
        "exported_at": timezone.now().isoformat(),
        "status": status or run.task_run.status,
        "task_status": run.task_run.status,
        "valid_comparison": invalid_reason is None,
        "invalid_reason": invalid_reason,
        "skill_name": launch.skill_name,
        "skill_version": launch.skill_version,
        "skill_body_sha256": hashlib.sha256(launch.skill_body.encode()).hexdigest(),
        "runtime": {field: getattr(launch, field) for field in _RUNTIME_FIELDS},
        "observed_runtime": {field: state.get(field) for field in _RUNTIME_FIELDS},
        "token_usage": state.get("token_usage"),
        "summary": run.summary,
        "metadata": cast(dict[str, JsonValue], run.metadata),
        "private_state": ScoutTrialStore(run).export(),
    }
    content = json.dumps(result)
    if len(content.encode()) > MAX_TRIAL_RESULT_BYTES:
        raise ValueError("The scout trial result is too large to export.")
    extras = {"ContentType": "application/json"}
    if status is None:
        # Polling may recover a missing export, but only the runner can replace a saved outcome.
        extras["IfNoneMatch"] = "*"
    try:
        object_storage.write(key, content, extras=extras)
    except object_storage.ObjectStorageError:
        if status is not None or read_trial_result(run) is None:
            raise
    return key
