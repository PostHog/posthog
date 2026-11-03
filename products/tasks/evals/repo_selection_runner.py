"""Run the production repository selector for one eval case.

Calls `select_repository` itself, so the prompt, candidate filtering, cache sync, sandbox
runtime, and result validation are the code production runs. The arm's model, runtime adapter,
reasoning effort, and service tier come from the harness context.
"""

from __future__ import annotations

import time
import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Literal

from pydantic import Field

from posthog.egress.limiter.policies import Priority
from posthog.temporal.common.client import async_connect

from products.posthog_ai.eval_harness.config import AgentArtifacts, SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.providers import SandboxProviderStrategy
from products.posthog_ai.eval_harness.runner import (
    EvalCaseResult,
    SandboxedCaseRunner,
    _finish_workflow,
    _parse_artifacts_from_log,
)
from products.tasks.backend.facade import api as tasks_api
from products.tasks.backend.facade.agents import CustomPromptSandboxContext, TurnPollTimeout
from products.tasks.backend.facade.contracts import TaskRunDTO
from products.tasks.backend.facade.repo_selection import (
    RepoSelectionRejectedError,
    RepoSelectionUnavailableError,
    RepoSelectionUsageLimitError,
    select_repository,
)
from products.tasks.backend.models import TaskRun

from .repo_selection_fixtures import RepoSelectionScenario

logger = logging.getLogger(__name__)

SelectorOutcome = Literal[
    "auto",  # the cascade picked a repository without the agent
    "no_repo",  # the needs-repo classifier decided no repository is needed
    "found",  # the agent picked a candidate
    "no_match",  # the agent returned null
    "rejected",  # the agent returned a repository outside the candidate list
    "unavailable",  # selection could not run (no eligible cached candidates)
    "usage_limited",  # the gateway refused the model calls with a 402
    "timeout",  # the selector outran its deadline
    "error",  # any other failure
    "not_run",  # an earlier stage ended the request
]

# Leaves room inside the harness case budget to read logs and tear the sandbox down, so a slow
# arm records a selector timeout instead of an infrastructure timeout.
SELECTOR_CLEANUP_RESERVE_SECONDS = 90


class RepoSelectionArtifacts(AgentArtifacts):
    stage: str = "selector"
    outcome: SelectorOutcome = "not_run"
    selected_repository: str | None = None
    reason: str = ""
    error_type: str | None = None
    selector_seconds: float | None = None
    task_id: str | None = None
    task_run_id: str | None = None
    distinct_id: str | None = None
    model: str | None = None
    runtime_adapter: str | None = None
    reasoning_effort: str | None = None
    requested_service_tier: str | None = None
    classifier_needs_repo: bool | None = None
    cascade_reason: str | None = None
    notes: list[str] = Field(default_factory=list)


def _latest_task_run(team_id: int) -> TaskRunDTO | None:
    run_id = TaskRun.objects.filter(team_id=team_id).order_by("-created_at").values_list("id", flat=True).first()
    return tasks_api.get_task_run(run_id, team_id=team_id) if run_id is not None else None


def _distinct_id(user_id: int) -> str | None:
    from posthog.models import User  # noqa: PLC0415 — keeps Django models off the harness import path

    return User.objects.filter(id=user_id).values_list("distinct_id", flat=True).first()


async def _finish(
    task_run: TaskRunDTO,
    *,
    successful: bool,
    provider: SandboxProviderStrategy,
    on_cleanup: Callable[[], Awaitable[None]] | None,
) -> None:
    if on_cleanup is not None:
        try:
            await on_cleanup()
        except Exception:
            logger.warning("Could not report cleanup progress", exc_info=True)
    try:
        client = await async_connect()
        await _finish_workflow(
            client.get_workflow_handle(task_run.workflow_id),
            status="completed" if successful else "failed",
            reason=None if successful else "Repository selection eval failed",
        )
    except Exception:
        logger.warning("Could not confirm repository selection workflow cleanup", exc_info=True)
    finally:
        await asyncio.to_thread(provider.cleanup_case, str(task_run.task_id))


async def run_selector(
    scenario: RepoSelectionScenario,
    context: CustomPromptSandboxContext,
    *,
    origin_product: tasks_api.TaskOriginProduct,
    priority: Priority,
    provider: SandboxProviderStrategy,
    on_cleanup: Callable[[], Awaitable[None]] | None,
    timeout_seconds: float | None,
    artifacts: RepoSelectionArtifacts | None = None,
) -> EvalCaseResult:
    """Run the selector on the scenario's thread and record what it decided and what it cost."""
    artifacts = artifacts or RepoSelectionArtifacts(exit_code=1)
    artifacts.model = context.model
    artifacts.runtime_adapter = context.runtime_adapter
    artifacts.reasoning_effort = context.reasoning_effort
    artifacts.requested_service_tier = context.service_tier
    artifacts.distinct_id = await asyncio.to_thread(_distinct_id, context.user_id)
    deadline = None if timeout_seconds is None else max(30.0, timeout_seconds - SELECTOR_CLEANUP_RESERVE_SECONDS)

    def _register(task_id: str, _run_id: str) -> None:
        provider.register_task(task_id)

    started = time.monotonic()
    try:
        result = await asyncio.wait_for(
            select_repository(
                team_id=context.team_id,
                user_id=context.user_id,
                context=scenario.context_block,
                origin_product=origin_product,
                priority=priority,
                model=context.model,
                runtime_adapter=context.runtime_adapter,
                reasoning_effort=context.reasoning_effort,
                service_tier=context.service_tier,
                on_research_session=_register,
            ),
            timeout=deadline,
        )
        artifacts.outcome = "found" if result.repository else "no_match"
        artifacts.selected_repository = result.repository
        artifacts.reason = result.reason
        artifacts.exit_code = 0
    except RepoSelectionRejectedError as error:
        artifacts.outcome = "rejected"
        artifacts.selected_repository = error.returned_repository
        artifacts.reason = error.reason
        # A pick outside the candidates is a model answer, so it is scored rather than excluded.
        artifacts.exit_code = 0
    except RepoSelectionUnavailableError as error:
        artifacts.outcome, artifacts.error_type, artifacts.stderr = "unavailable", type(error).__name__, error.reason
    except RepoSelectionUsageLimitError as error:
        artifacts.outcome, artifacts.error_type, artifacts.stderr = "usage_limited", type(error).__name__, error.message
    except TimeoutError:
        artifacts.outcome, artifacts.error_type = "timeout", "TimeoutError"
        artifacts.stderr = f"selector deadline of {deadline:.0f}s passed"
    except Exception as error:
        logger.warning("Repository selection eval failed", exc_info=True)
        artifacts.outcome, artifacts.error_type, artifacts.stderr = "error", type(error).__name__, str(error)[:2000]
    artifacts.selector_seconds = time.monotonic() - started

    task_run = await asyncio.to_thread(_latest_task_run, context.team_id)
    raw_log = ""
    if task_run is not None:
        provider.register_task(str(task_run.task_id))
        artifacts.task_id, artifacts.task_run_id = str(task_run.task_id), str(task_run.id)
        try:
            conversation = await asyncio.to_thread(
                tasks_api.read_task_run_conversation_logs, task_run.id, task_run.task_id, context.team_id
            )
            raw_log = conversation or ""
        except Exception:
            logger.warning("Could not read the selector's agent log", exc_info=True)
            artifacts.notes.append("agent log unavailable")
        await _finish(task_run, successful=artifacts.exit_code == 0, provider=provider, on_cleanup=on_cleanup)
    parsed = _parse_artifacts_from_log(raw_log, artifacts.selector_seconds, agent_finished=artifacts.exit_code == 0)
    merged = artifacts.model_copy(
        update={
            **{key: value for key, value in parsed.model_dump().items() if key not in {"exit_code", "stderr"}},
            "stderr": artifacts.stderr or parsed.stderr,
        }
    )
    return EvalCaseResult(artifacts=merged, raw_log=raw_log, trace_id=artifacts.task_run_id or "")


def selector_case_runner(
    scenarios: dict[str, RepoSelectionScenario], *, origin_product: tasks_api.TaskOriginProduct, priority: Priority
) -> SandboxedCaseRunner:
    async def run(
        case: SandboxedEvalCase,
        context: CustomPromptSandboxContext,
        *,
        provider: SandboxProviderStrategy,
        on_cleanup: Callable[[], Awaitable[None]] | None = None,
        timeout_seconds: float | None = None,
        on_poll_timeout: Callable[[TurnPollTimeout], None] | None = None,
    ) -> EvalCaseResult:
        return await run_selector(
            scenarios[case.name],
            context,
            origin_product=origin_product,
            priority=priority,
            provider=provider,
            on_cleanup=on_cleanup,
            timeout_seconds=timeout_seconds,
        )

    return run
