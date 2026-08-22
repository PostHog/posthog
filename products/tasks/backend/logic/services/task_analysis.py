"""Server-side creation of task-analysis runs.

A task analysis is a PostHog-funded cloud task (origin ``task_analysis``) that reviews another
run's transcript for inefficiencies. The target run's durable log is copied into the analysis
run's artifacts so the sandbox materializes it as a file — the log never travels through a model
context or a client. Creation is server-only: the origin routes to PostHog-funded billing
exclusions, so exposing it to API callers would hand out free model access.
"""

import uuid
from typing import Any

import structlog

from posthog.models.team import Team
from posthog.storage import object_storage

from products.tasks.backend.logic.services.staged_artifacts import (
    RUN_ARTIFACT_TTL_DAYS,
    build_task_artifact_entry,
    build_task_run_artifact_storage_path,
    tag_task_artifact,
)
from products.tasks.backend.models import Task, TaskRun

logger = structlog.get_logger(__name__)

TASK_ANALYSIS_MODEL = "deepseek-ai/deepseek-v4-flash-0731"
TASK_ANALYSIS_RUNTIME_ADAPTER = "claude"
ANALYSIS_TARGET_TASK_ID_STATE_KEY = "analysis_target_task_id"
ANALYSIS_TARGET_RUN_ID_STATE_KEY = "analysis_target_run_id"
RUN_LOG_ARTIFACT_NAME = "run-log.jsonl"

# Names the analyzing-task-runs skill (served through the PostHog MCP) the way scout chats name
# theirs, with an inline fallback so a run without the skill still follows the load-bearing
# rules: never read the raw log, report through the tool, never invent findings.
ANALYSIS_PROMPT_TEMPLATE = """Use the analyzing-task-runs skill from the PostHog MCP to analyze task {target_task_id} run {target_run_id} for inefficiencies. The run's log is attached to this task as {artifact_name}.

If the skill is unavailable: do NOT read the attached log directly (it can be tens of megabytes); state that the analysis cannot run without the skill and stop. Report findings only through the report_insight tool, one finding per call, each with verbatim evidence from the extracted transcript. Zero findings is a valid result."""


class TaskAnalysisError(Exception):
    """A task analysis could not be created; ``message`` is safe to surface to the caller."""


def find_existing_analysis_task(*, team_id: int, target_run_id: str) -> Task | None:
    run = (
        TaskRun.objects.filter(
            team_id=team_id,
            task__origin_product=Task.OriginProduct.TASK_ANALYSIS,
            state__analysis_target_run_id=str(target_run_id),
        )
        .select_related("task")
        .order_by("-created_at")
        .first()
    )
    return run.task if run is not None else None


def create_task_analysis(*, team: Team, user_id: int, target_task: Task, target_run: TaskRun) -> tuple[Task, bool]:
    """Create (or return the existing) analysis task for ``target_run``.

    Returns ``(task, created)``. The analysis task is created without starting its workflow,
    the target run's log is copied into the new run's artifact manifest, and only then is the
    workflow dispatched — so the sandbox can never boot before its attachment exists.
    """
    from products.tasks.backend.logic.services.workflow_dispatch import (  # noqa: PLC0415 — temporal client stays off the module import path
        WorkflowDispatchOptions,
        enqueue_or_start_workflow,
    )

    existing = find_existing_analysis_task(team_id=team.id, target_run_id=str(target_run.id))
    if existing is not None:
        return existing, False

    log_content = object_storage.read_bytes(target_run.log_url, missing_ok=True)
    if not log_content:
        raise TaskAnalysisError("The run has no log to analyze yet.")

    artifact_id = str(uuid.uuid4())
    prompt = ANALYSIS_PROMPT_TEMPLATE.format(
        target_task_id=target_task.id,
        target_run_id=target_run.id,
        artifact_name=RUN_LOG_ARTIFACT_NAME,
    )
    extra_run_state: dict[str, Any] = {
        ANALYSIS_TARGET_TASK_ID_STATE_KEY: str(target_task.id),
        ANALYSIS_TARGET_RUN_ID_STATE_KEY: str(target_run.id),
        "pending_user_artifact_ids": [artifact_id],
    }

    task = Task.create_and_run(
        team=team,
        title=f"Task analysis: {target_task.title[:120]}",
        description=prompt,
        origin_product=Task.OriginProduct.TASK_ANALYSIS,
        user_id=user_id,
        repository=None,
        create_pr=False,
        mode="background",
        start_workflow=False,
        runtime_adapter=TASK_ANALYSIS_RUNTIME_ADAPTER,
        model=TASK_ANALYSIS_MODEL,
        pending_user_message=prompt,
        extra_run_state=extra_run_state,
    )
    run = task.latest_run
    if run is None:  # pragma: no cover — create_and_run always creates a run
        raise TaskAnalysisError("Task creation did not produce a run.")

    storage_path = build_task_run_artifact_storage_path(run, artifact_id, RUN_LOG_ARTIFACT_NAME)
    object_storage.write(storage_path, log_content)
    tag_task_artifact(storage_path, ttl_days=RUN_ARTIFACT_TTL_DAYS, team_id=team.id)
    run.artifacts = [
        build_task_artifact_entry(
            artifact_id=artifact_id,
            name=RUN_LOG_ARTIFACT_NAME,
            artifact_type="file",
            source="task_analysis",
            size=len(log_content),
            content_type="application/x-ndjson",
            storage_path=storage_path,
        )
    ]
    run.save(update_fields=["artifacts", "updated_at"])

    logger.info(
        "task_analysis.created",
        task_id=str(task.id),
        run_id=str(run.id),
        target_task_id=str(target_task.id),
        target_run_id=str(target_run.id),
        log_bytes=len(log_content),
    )

    enqueue_or_start_workflow(
        run,
        options=WorkflowDispatchOptions(
            user_id=user_id,
            create_pr=False,
            slack_thread_context=None,
            posthog_mcp_scopes="full",
            workflow_id_prefix=None,
        ),
    )
    return task, True
