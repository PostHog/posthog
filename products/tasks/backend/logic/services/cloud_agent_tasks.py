"""Create, resume and read the tasks behind the Cloud Agents public API.

The Cloud Agents product owns its API contract, its limits and its usage ledger. Everything
task-shaped happens here, so that product never touches tasks internals. Each function is
scoped to the reserved ``cloud_agents`` origin: a task of another origin is never found.
"""

import json
from collections.abc import Collection, Mapping
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Min, OuterRef, QuerySet, Subquery, Value
from django.db.models.functions import Coalesce

from jsonschema import Draft202012Validator, SchemaError

from posthog.dataclasses import frozen
from posthog.models import User
from posthog.models.team.team import Team

from products.tasks.backend.constants import PR_STATES
from products.tasks.backend.exceptions import COMPUTE_USAGE_LIMIT_ERROR_MESSAGE
from products.tasks.backend.facade import (
    api as tasks_api,
    contracts,
)
from products.tasks.backend.feature_flags import get_model_access_error
from products.tasks.backend.logic.model_access import INFERENCE_STATE_KEYS
from products.tasks.backend.logic.services.gateway_usage import get_tasks_billing
from products.tasks.backend.logic.services.inference_resolution import validated_inference_state
from products.tasks.backend.logic.services.model_catalogue import runtime_adapter_for
from products.tasks.backend.logic.services.sandbox_config import (
    SANDBOX_SIZE_SHAPES,
    SANDBOX_SIZE_STATE_KEY,
    SandboxSize,
)
from products.tasks.backend.logic.services.sandbox_pricing import compute_waived
from products.tasks.backend.logic.services.workflow_task_output import RUN_OUTPUT_RESERVED_KEYS
from products.tasks.backend.models import SandboxSession, Task, TaskClientProvenance, TaskRun
from products.tasks.backend.pr_urls import read_pr_urls
from products.tasks.backend.temporal.process_task.activities.update_task_run_status import (
    TIMED_OUT_INACTIVITY_STATE_KEY,
    TIMED_OUT_WALL_CLOCK_STATE_KEY,
)
from products.tasks.backend.temporal.process_task.utils import (
    RuntimeAdapter,
    get_default_model_for_runtime_adapter,
    validate_model_selection,
)

ACTIVE_RUN_STATUSES = [TaskRun.Status.NOT_STARTED, TaskRun.Status.QUEUED, TaskRun.Status.IN_PROGRESS]

# The PostHog MCP posture of every Cloud Agents run. An unattended run that an API key
# started must not write to the project.
CLOUD_AGENT_POSTHOG_MCP_SCOPES: Literal["read_only"] = "read_only"

TaskRunEnd = contracts.TaskRunEnd

OUTPUT_SCHEMA_MAX_BYTES = 16 * 1024
# The keys of a run output that Tasks writes. Every other key is a field that the agent returned.
_TASKS_OUTPUT_KEYS = RUN_OUTPUT_RESERVED_KEYS | frozenset(tasks_api._INHERITED_PR_OUTPUT_KEYS)

_WAITING_RUN_STATUSES = (TaskRun.Status.NOT_STARTED, TaskRun.Status.QUEUED)


class CloudAgentTaskError(Exception):
    """Base for the refusals below. ``attr`` names the request field at fault, if one is."""

    def __init__(self, detail: str, *, attr: str | None = None) -> None:
        self.detail = detail
        self.attr = attr
        super().__init__(detail)


class CloudAgentTaskInvalid(CloudAgentTaskError):
    pass


class CloudAgentTaskNotFound(CloudAgentTaskError):
    pass


class CloudAgentRunNotResumable(CloudAgentTaskError):
    pass


class CloudAgentTaskOriginKeyConflict(CloudAgentTaskError):
    def __init__(self, origin_key: str) -> None:
        self.origin_key = origin_key
        super().__init__(f"Idempotency key {origin_key!r} is already used by another task", attr="origin_key")


def create_cloud_agent_task(
    *,
    team_id: int,
    user_id: int,
    prompt: str,
    title: str,
    repository: str,
    branch: str | None,
    create_pr: bool,
    origin_key: str | None,
    billable: bool,
    sandbox_size: SandboxSize,
    model: str | None,
    runtime_adapter: str | None,
    reasoning_effort: str | None,
    inactivity_timeout_seconds: int | None,
    extra_run_state: Mapping[str, object] | None,
    inference_state: Mapping[str, object] | None = None,
    output_schema: Mapping[str, object] | None = None,
) -> contracts.CloudAgentTaskDTO:
    """Create a Cloud Agents task and start its first run.

    A repeated ``origin_key`` returns the existing task with ``created=False``, before any
    other check, so that a retry succeeds when the first attempt did. Raises
    ``CloudAgentTaskOriginKeyConflict`` when the key belongs to a task of another origin, and
    ``CloudAgentTaskInvalid`` when the model selection is not allowed.

    ``billable`` is carried as the task's client provenance. Each sandbox session that a run of
    the task opens copies it, which is how the usage ledger finds the sessions to bill.

    The sandbox has the fixed shape of ``sandbox_size``, the default size included, so that
    the usage record of each session states the full selected shape.

    ``inference_state`` is ``InferenceDecision.run_state_updates`` from ``facade.inference``. It
    selects who pays for model use, and ``user_id`` becomes the owner of the selected credential.
    ``None`` is a run on PostHog credits. ``extra_run_state`` must not carry these keys.

    ``output_schema`` is a JSON Schema for the result of the task. With a schema, each run of
    the task must return a result that matches it, and the run completes when it does. Check
    the schema with ``validate_cloud_agent_output_schema`` first: an invalid one raises
    ``CloudAgentTaskInvalid`` here too.
    """
    _refuse_inference_keys(extra_run_state)
    replay = _find_replayed_task(team_id, origin_key)
    if replay is not None:
        return replay
    if output_schema is not None:
        validate_cloud_agent_output_schema(output_schema)

    selection = _resolve_model_selection(
        user_id=user_id, model=model, runtime_adapter=runtime_adapter, reasoning_effort=reasoning_effort
    )
    run_state: dict[str, Any] = {
        **(extra_run_state or {}),
        **validated_inference_state(inference_state),
        **_sized_run_state(sandbox_size),
        # The boot path reads the override and delivers the prompt one time. A pending user
        # message is delivered at boot and forwarded again for a cold background run.
        "initial_prompt_override": prompt,
    }
    team = Team.objects.get(id=team_id)
    try:
        # One transaction so that a duplicate origin_key rolls back the task, its run and the
        # workflow start, which is deferred to the commit.
        with transaction.atomic():
            task = Task.create_and_run(
                team=team,
                title=title.strip()[:255] or prompt[:255],
                description=prompt,
                origin_product=Task.OriginProduct.CLOUD_AGENTS,
                user_id=user_id,
                repository=repository,
                branch=branch,
                mode="background",
                create_pr=create_pr,
                posthog_mcp_scopes=CLOUD_AGENT_POSTHOG_MCP_SCOPES,
                origin_key=origin_key,
                internal=True,
                output_schema=dict(output_schema) if output_schema is not None else None,
                client_provenance=TaskClientProvenance.CLOUD_AGENTS if billable else None,
                # An internal task gets no AI run defaults from Tasks, so the selection is pinned here.
                runtime_adapter=selection.runtime_adapter,
                model=selection.model,
                reasoning_effort=reasoning_effort,
                sandbox_resources=SANDBOX_SIZE_SHAPES[sandbox_size],
                inactivity_timeout_seconds=inactivity_timeout_seconds,
                extra_run_state=run_state,
            )
    except IntegrityError:
        if origin_key is None:
            raise
        replay = _find_replayed_task(team_id, origin_key)
        if replay is None:
            raise
        return replay
    return _task_dto(task, created=True)


def resume_cloud_agent_task(
    *,
    team_id: int,
    task_id: UUID,
    user_id: int,
    previous_run_id: UUID,
    message: str,
    sandbox_size: SandboxSize,
    model: str | None,
    reasoning_effort: str | None,
    inactivity_timeout_seconds: int | None,
    extra_run_state: Mapping[str, object] | None,
    inference_state: Mapping[str, object] | None = None,
) -> contracts.TaskRunDTO:
    """Start a successor run that resumes ``previous_run_id`` with ``message`` as its first turn.

    The task lookup is scoped to the origin and the team, not to what ``user_id`` can see in
    Tasks: the Cloud Agents product authorizes its own callers. ``model`` and
    ``reasoning_effort`` left as ``None`` keep the selection of the previous run.

    ``inference_state`` is ``InferenceDecision.run_state_updates`` from ``facade.inference``, and
    it replaces the inference mode of the previous run. ``None`` keeps the mode of the previous
    run. In both cases ``user_id`` becomes the owner of the credential, so the run never uses the
    credential of another user.

    Raises ``CloudAgentTaskNotFound`` for an unknown task, ``CloudAgentRunNotResumable`` when
    the previous run is unknown, still active or owned by an earlier task owner, and
    ``CloudAgentTaskInvalid`` when the request is refused for another reason.
    """
    _refuse_inference_keys(extra_run_state)
    inference = validated_inference_state(inference_state) if inference_state is not None else {}
    task = _cloud_agent_tasks(team_id).filter(id=task_id).first()
    if task is None:
        raise CloudAgentTaskNotFound("Task not found")
    previous_run = task.runs.filter(id=previous_run_id).first()
    if previous_run is None:
        raise CloudAgentRunNotResumable("The previous run does not belong to this task", attr="previous_run_id")
    if not previous_run.is_terminal:
        raise CloudAgentRunNotResumable("The previous run is still active", attr="previous_run_id")

    previous_dispatch = (previous_run.state or {}).get("pending_dispatch")
    previous_create_pr = previous_dispatch.get("create_pr") if isinstance(previous_dispatch, dict) else None
    create_pr = previous_create_pr if isinstance(previous_create_pr, bool) else True

    server_run_state: dict[str, Any] = {
        **(extra_run_state or {}),
        **inference,
        **_sized_run_state(sandbox_size),
        # The same record the first run has, so that a lost workflow start is dispatched again
        # with the same PR and scope settings.
        "pending_dispatch": {
            "create_pr": create_pr,
            "posthog_mcp_scopes": CLOUD_AGENT_POSTHOG_MCP_SCOPES,
            "user_id": user_id,
        },
    }
    if inactivity_timeout_seconds is not None:
        server_run_state["inactivity_timeout_seconds"] = inactivity_timeout_seconds

    result = tasks_api._run_resolved_task(
        task,
        team_id,
        user_id,
        validated_data={
            "mode": "background",
            "resume_from_run_id": previous_run.id,
            "pending_user_message": message,
            "model": model,
            "runtime_adapter": runtime_adapter_for(model) if model else None,
            "reasoning_effort": reasoning_effort,
        },
        server_run_state=server_run_state,
        create_pr=create_pr,
        posthog_mcp_scopes=CLOUD_AGENT_POSTHOG_MCP_SCOPES,
    )
    if result is None:
        raise CloudAgentRunNotResumable(
            "The previous run belongs to an earlier owner of the task", attr="previous_run_id"
        )
    if result.error is not None:
        if result.error.attr is None:
            raise CloudAgentRunNotResumable(result.error.detail, attr="previous_run_id")
        raise CloudAgentTaskInvalid(result.error.detail, attr=result.error.attr)
    run = get_cloud_agent_task_run(team_id=team_id, run_id=result.run_id) if result.run_id else None
    if run is None:
        raise CloudAgentRunNotResumable("The successor run was not created", attr="previous_run_id")
    return run


def validate_cloud_agent_output_schema(schema: object) -> None:
    """Raise ``CloudAgentTaskInvalid`` unless ``schema`` can be the output schema of a Cloud Agents task.

    The result of a run is one JSON object that shares the run output with the fields that Tasks
    writes there. So the schema must describe an object, and its properties must not use a name
    that Tasks writes.
    """
    if not isinstance(schema, Mapping):
        raise CloudAgentTaskInvalid("The output schema must be a JSON object.", attr="output_schema")
    try:
        size = len(json.dumps(schema))
    except (TypeError, ValueError):
        raise CloudAgentTaskInvalid("The output schema must be valid JSON.", attr="output_schema") from None
    if size > OUTPUT_SCHEMA_MAX_BYTES:
        raise CloudAgentTaskInvalid(
            f"The output schema is too large. Use {OUTPUT_SCHEMA_MAX_BYTES} bytes of JSON at most.",
            attr="output_schema",
        )
    if schema.get("type") != "object":
        raise CloudAgentTaskInvalid('The output schema must have `"type": "object"`.', attr="output_schema")
    properties = schema.get("properties")
    reserved = sorted(_TASKS_OUTPUT_KEYS & set(properties)) if isinstance(properties, Mapping) else []
    if reserved:
        raise CloudAgentTaskInvalid(
            f"These property names are reserved. Use different names: {', '.join(reserved)}.", attr="output_schema"
        )
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as error:
        raise CloudAgentTaskInvalid(
            f"The output schema is not a valid JSON Schema: {error.message}", attr="output_schema"
        ) from None


def classify_task_run_end(run: contracts.TaskRunDTO) -> TaskRunEnd:
    """Why a finished run ended. Raises ``ValueError`` for a run that is still active.

    A completed run is ``done`` even with a timeout marker: the workflow completes an idle
    run whose turn ended, and marks it, when no client ended it first. A failed run with a
    timeout marker stopped in the middle of a turn, so it is ``timeout``.
    """
    if not run.is_terminal:
        raise ValueError(f"Task run {run.id} has not ended (status {run.status})")
    return _classify_end(run.status, run.error_message, run.state)


def _classify_end(status: str, error_message: str | None, state: Mapping[str, Any]) -> TaskRunEnd:
    if status == TaskRun.Status.CANCELLED:
        return "cancelled"
    if status == TaskRun.Status.COMPLETED:
        return "done"
    if (error_message or "").startswith(COMPUTE_USAGE_LIMIT_ERROR_MESSAGE):
        return "usage_limit"
    if state.get(TIMED_OUT_INACTIVITY_STATE_KEY) or state.get(TIMED_OUT_WALL_CLOCK_STATE_KEY):
        return "timeout"
    return "error"


def count_active_cloud_agent_runs(*, team_id: int) -> int:
    """Runs of this origin that have not ended. Soft-deleting a task does not stop its run, so
    the runs of deleted tasks count."""
    return TaskRun.objects.filter(
        team_id=team_id,
        task__team_id=team_id,
        task__origin_product=Task.OriginProduct.CLOUD_AGENTS,
        status__in=ACTIVE_RUN_STATUSES,
    ).count()


def get_cloud_agent_task_run(*, team_id: int, run_id: UUID) -> contracts.TaskRunDTO | None:
    """A run by id, only when it belongs to a Cloud Agents task of this team.

    ``get_task_run`` is scoped to the team at most, so a caller that holds only a run id would
    read the run of any task through it.
    """
    run = (
        TaskRun.objects.select_related("task", "task__created_by")
        .filter(id=run_id, team_id=team_id, task__team_id=team_id, task__origin_product=Task.OriginProduct.CLOUD_AGENTS)
        .first()
    )
    return tasks_api._task_run_to_dto(run) if run is not None else None


def list_cloud_agent_task_run_ids(*, team_id: int, task_id: UUID) -> list[UUID]:
    """Every run of the task, oldest first. Each run after the first resumes the one before it."""
    return list(
        TaskRun.objects.filter(
            team_id=team_id,
            task_id=task_id,
            task__team_id=team_id,
            task__origin_product=Task.OriginProduct.CLOUD_AGENTS,
        )
        .order_by("created_at", "id")
        .values_list("id", flat=True)
    )


def get_cloud_agent_task_states(
    *, team_id: int, task_ids: Collection[UUID]
) -> dict[UUID, contracts.CloudAgentTaskStateDTO]:
    """Where each task in ``task_ids`` stands. Three queries for any number of tasks.

    Every requested id is a key of the result. An id with no run of this origin in this team
    reads as a queued task with no run, so the caller cannot tell it from a task that waits.
    """
    states = {task_id: _state_without_runs(task_id) for task_id in task_ids}
    if not states:
        return states
    runs_by_task: dict[UUID, list[TaskRun]] = {}
    runs = (
        _cloud_agent_runs(team_id)
        .filter(task_id__in=list(states))
        # The other columns of a run are not read, and some of them are large.
        .only("id", "task_id", "status", "error_message", "output", "state", "created_at", "updated_at", "completed_at")
        .order_by("created_at", "id")
    )
    for run in runs:
        runs_by_task.setdefault(run.task_id, []).append(run)
    if not runs_by_task:
        return states
    sandbox_started_at: dict[UUID, datetime] = dict(
        SandboxSession.objects.for_team(team_id)
        .filter(task_run_id__in=[run.id for task_runs in runs_by_task.values() for run in task_runs])
        .values("task_run_id")
        .annotate(first_created_at=Min("created_at"))
        .values_list("task_run_id", "first_created_at")
    )
    for task_id, task_runs in runs_by_task.items():
        states[task_id] = _task_state(task_id, task_runs, sandbox_started_at)
    return states


def get_cloud_agent_tasks_billing(
    *, team_id: int, task_ids: Collection[UUID]
) -> dict[UUID, contracts.TaskRunBillingDTO]:
    """The charges of each task in ``task_ids``. Three queries for any number of tasks.

    Every requested id is a key of the result. An id that is not a task of this origin in this
    team has no charge.
    """
    return get_tasks_billing(team_id=team_id, task_ids=task_ids, origin_product=Task.OriginProduct.CLOUD_AGENTS)


def list_cloud_agent_task_ids(
    *,
    team_id: int,
    statuses: Collection[str],
    limit: int,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
) -> list[UUID]:
    """The newest ``limit`` tasks of this origin whose latest run has one of ``statuses``. One query.

    ``created_after`` and ``created_before`` keep the tasks created from the first up to, and not
    at, the second. A task with no run counts as queued. Soft-deleted tasks are included, because
    the caller keeps its own record of them.
    """
    tasks = Task.objects.filter(team_id=team_id, origin_product=Task.OriginProduct.CLOUD_AGENTS)
    if created_after is not None:
        tasks = tasks.filter(created_at__gte=created_after)
    if created_before is not None:
        tasks = tasks.filter(created_at__lt=created_before)
    latest_status = (
        TaskRun.objects.filter(task_id=OuterRef("pk"), team_id=team_id)
        .order_by("-created_at", "-id")
        .values("status")[:1]
    )
    return list(
        tasks.annotate(latest_status=Coalesce(Subquery(latest_status), Value(TaskRun.Status.QUEUED.value)))
        .filter(latest_status__in=list(statuses))
        .order_by("-created_at", "-id")
        .values_list("id", flat=True)[:limit]
    )


def list_active_billable_cloud_agent_runs(*, team_id: int, limit: int) -> list[contracts.CloudAgentActiveRunDTO]:
    """The oldest ``limit`` runs of the team that have not ended and that the team pays for. One query."""
    runs = (
        _cloud_agent_runs(team_id)
        .filter(status__in=ACTIVE_RUN_STATUSES, task__client_provenance=TaskClientProvenance.CLOUD_AGENTS)
        .order_by("created_at", "id")
        .values_list("task_id", "id")[:limit]
    )
    return [contracts.CloudAgentActiveRunDTO(task_id=task_id, task_run_id=run_id) for task_id, run_id in runs]


def summarize_cloud_agent_usage(
    *, team_id: int, date_from: datetime, date_to: datetime, limit: int
) -> contracts.CloudAgentUsageDTO:
    """The charges of the tasks created from ``date_from`` up to, and not at, ``date_to``. Four queries.

    One row for each task, so the caller can group the rows by day or by its own record of a task.
    At most ``limit`` rows, for the newest tasks.
    """
    tasks = list(
        Task.objects.filter(
            team_id=team_id,
            origin_product=Task.OriginProduct.CLOUD_AGENTS,
            created_at__gte=date_from,
            created_at__lt=date_to,
        )
        .order_by("-created_at", "-id")
        .values_list("id", "created_at")[: limit + 1]
    )
    truncated = len(tasks) > limit
    tasks = tasks[:limit]
    billing = get_cloud_agent_tasks_billing(team_id=team_id, task_ids=[task_id for task_id, _ in tasks])
    return contracts.CloudAgentUsageDTO(
        rows=tuple(
            contracts.CloudAgentTaskUsageDTO(
                task_id=task_id,
                created_at=created_at,
                compute_cost_cents=billing[task_id].compute_cost_cents,
                inference_cost_cents=billing[task_id].inference_cost_cents,
                vcpu_seconds=billing[task_id].vcpu_seconds,
                gib_seconds=billing[task_id].gib_seconds,
                inference_billing=billing[task_id].inference_billing,
            )
            for task_id, created_at in tasks
        ),
        truncated=truncated,
    )


def _cloud_agent_runs(team_id: int) -> QuerySet[TaskRun]:
    return TaskRun.objects.filter(
        team_id=team_id, task__team_id=team_id, task__origin_product=Task.OriginProduct.CLOUD_AGENTS
    )


def _state_without_runs(task_id: UUID) -> contracts.CloudAgentTaskStateDTO:
    return contracts.CloudAgentTaskStateDTO(
        task_id=task_id,
        status=TaskRun.Status.QUEUED.value,
        run_end=None,
        cancel_source=None,
        compute_waived=False,
        current_task_run_id=None,
        started_at=None,
        completed_at=None,
        updated_at=None,
        pr_url=None,
        pr_urls=(),
        pull_requests=(),
        summary=None,
        structured_output=None,
        sessions=(),
    )


def _task_state(
    task_id: UUID, runs: list[TaskRun], sandbox_started_at: Mapping[UUID, datetime]
) -> contracts.CloudAgentTaskStateDTO:
    """``runs`` are the runs of the task, oldest first."""
    sessions: list[contracts.CloudAgentSessionDTO] = []
    for index, run in enumerate(runs, start=1):
        # A run has no start time of its own. Its sandbox gives the time, and a run that left
        # the queue with no sandbox on record gives the time it was created.
        started_at = sandbox_started_at.get(run.id)
        if started_at is None and run.status not in _WAITING_RUN_STATUSES:
            started_at = run.created_at
        sessions.append(
            contracts.CloudAgentSessionDTO(
                index=index,
                task_run_id=run.id,
                status=run.status,
                started_at=started_at,
                ended_at=(run.completed_at or run.updated_at) if run.is_terminal else None,
            )
        )
    latest = runs[-1]
    latest_state = latest.state or {}
    cancel_source = latest_state.get("cancel_source")
    # A later run can open one more pull request, so the list keeps the earlier ones.
    pr_urls = tuple(dict.fromkeys(url for run in runs for url in read_pr_urls(run.output)))
    latest_pr_url = next(
        (url for run in reversed(runs) if isinstance(url := (run.output or {}).get("pr_url"), str) and url), None
    )
    return contracts.CloudAgentTaskStateDTO(
        task_id=task_id,
        status=latest.status,
        run_end=_classify_end(latest.status, latest.error_message, latest_state) if latest.is_terminal else None,
        cancel_source=cancel_source if isinstance(cancel_source, str) else None,
        compute_waived=compute_waived("cloud_agents", latest_state),
        current_task_run_id=latest.id,
        started_at=next((session.started_at for session in sessions if session.started_at is not None), None),
        completed_at=sessions[-1].ended_at,
        updated_at=max(run.updated_at for run in runs),
        pr_url=latest_pr_url or (pr_urls[0] if pr_urls else None),
        pr_urls=pr_urls,
        pull_requests=tuple(
            contracts.CloudAgentPullRequestDTO(url=url, state=_pull_request_state(url, runs)) for url in pr_urls
        ),
        summary=next((summary for run in reversed(runs) if (summary := run.task_summary)), None),
        structured_output=next((fields for run in reversed(runs) if (fields := _agent_output_fields(run))), None),
        sessions=tuple(sessions),
    )


def _pull_request_state(url: str, runs: list[TaskRun]) -> contracts.PullRequestState | None:
    """What the newest run that points at the pull request recorded for it.

    A run output holds the state of its primary pull request only, so another pull request of
    the same run has no state.
    """
    for run in reversed(runs):
        output = run.output if isinstance(run.output, dict) else {}
        if output.get("pr_url") != url:
            continue
        if output.get("pr_merged") is True:
            return "merged"
        state = output.get("pr_state")
        if state in PR_STATES:
            return state
    return None


def _agent_output_fields(run: TaskRun) -> dict[str, Any]:
    output = run.output if isinstance(run.output, dict) else {}
    return {key: value for key, value in output.items() if key not in _TASKS_OUTPUT_KEYS}


def _refuse_inference_keys(extra_run_state: Mapping[str, object] | None) -> None:
    # A key that was silently dropped here would turn a run on the user's own credential into a
    # run on PostHog credits, so this is an error and not a filter.
    carried = sorted(
        key for key in (extra_run_state or {}) if key in INFERENCE_STATE_KEYS or key.endswith("_subscription_user_id")
    )
    if carried:
        raise ValueError(f"Pass {', '.join(carried)} through inference_state, not extra_run_state")


def _cloud_agent_tasks(team_id: int) -> QuerySet[Task]:
    return Task.objects.filter(team_id=team_id, origin_product=Task.OriginProduct.CLOUD_AGENTS, deleted=False)


def _sized_run_state(sandbox_size: SandboxSize) -> dict[str, Any]:
    """The run state that pins a run to a fixed sandbox shape.

    The CPU and memory keys are repeated here because a successor run gets no
    ``sandbox_resources`` argument: its state is the only place the shape can come from.
    """
    shape = SANDBOX_SIZE_SHAPES[sandbox_size]
    return {
        SANDBOX_SIZE_STATE_KEY: sandbox_size.value,
        "sandbox_cpu_cores": shape.cpu_cores,
        "sandbox_memory_gb": shape.memory_gb,
        # Request equals limit, so the usage record of the session states the full shape.
        "burstable_sandbox_resources_enabled": False,
        # Gives the agent the `finish` tool, so the sandbox is released when the work is done
        # and not at the inactivity timeout.
        "end_run_when_done": True,
    }


@frozen
class _ModelSelection:
    runtime_adapter: str
    model: str | None


def _resolve_model_selection(
    *, user_id: int, model: str | None, runtime_adapter: str | None, reasoning_effort: str | None
) -> _ModelSelection:
    adapter = runtime_adapter or runtime_adapter_for(model) or RuntimeAdapter.CLAUDE.value
    resolved_model = model or get_default_model_for_runtime_adapter(adapter)
    try:
        validate_model_selection(adapter, resolved_model, reasoning_effort)
    except ValidationError as error:
        raise CloudAgentTaskInvalid("; ".join(error.messages), attr="model") from error
    distinct_id = User.objects.filter(id=user_id).values_list("distinct_id", flat=True).first()
    access_error = get_model_access_error(resolved_model, distinct_id=distinct_id)
    if access_error is not None:
        raise CloudAgentTaskInvalid(access_error, attr="model")
    return _ModelSelection(runtime_adapter=adapter, model=resolved_model)


def _find_replayed_task(team_id: int, origin_key: str | None) -> contracts.CloudAgentTaskDTO | None:
    if origin_key is None:
        return None
    existing = Task.objects.filter(team_id=team_id, origin_key=origin_key).first()
    if existing is None:
        return None
    if existing.origin_product != Task.OriginProduct.CLOUD_AGENTS:
        raise CloudAgentTaskOriginKeyConflict(origin_key)
    return _task_dto(existing, created=False)


def _task_dto(task: Task, *, created: bool) -> contracts.CloudAgentTaskDTO:
    run = task.latest_run
    return contracts.CloudAgentTaskDTO(
        task_id=task.id,
        team_id=task.team_id,
        run=tasks_api._task_run_to_dto(run, task=task) if run is not None else None,
        created=created,
    )
