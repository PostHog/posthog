from __future__ import annotations

import json
import time
import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime

from django.utils import timezone

from pydantic import BaseModel, Field

from posthog.models import Team, User
from posthog.temporal.common.client import async_connect

from products.posthog_ai.eval_harness.config import AgentArtifacts, SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.providers import SandboxProviderStrategy
from products.posthog_ai.eval_harness.runner import (
    EvalCaseResult,
    WorkflowCleanupError,
    _finish_workflow,
    _parse_artifacts_from_log,
    _report_cleanup,
)
from products.signals.backend.agent_runtime import AgentRuntime
from products.signals.backend.constants import FIRST_REPORT_SCOUT
from products.signals.backend.first_report_scout import build_first_report_context, first_report_state
from products.signals.backend.first_report_scout_types import FirstReportScoutResult
from products.signals.backend.models import (
    SignalReport,
    SignalScoutConfig,
    SignalScoutRun,
    SignalSourceConfig,
    SignalTeamConfig,
)
from products.signals.backend.scout_harness.limits import TRIGGERED_BY_ONBOARDING
from products.signals.backend.scout_harness.runner import arun_signals_scout
from products.signals.backend.scout_harness.tools.profile import compute_project_profile
from products.tasks.backend.facade import api as tasks_api
from products.tasks.backend.facade.agents import CustomPromptSandboxContext, TurnPollTimeout
from products.tasks.backend.facade.contracts import TaskRunDTO

logger = logging.getLogger(__name__)


class EvalReport(BaseModel):
    id: str
    title: str
    summary: str
    status: str
    visible_after_seconds: float | None


class ScoutArtifacts(AgentArtifacts):
    reports: list[EvalReport] = Field(default_factory=list)
    last_message: str | None = None
    scout_closeout: str | None = None
    outcome: str = "incomplete"
    missing_data: list[str] = Field(default_factory=list)
    checked_products: list[str] = Field(default_factory=list)
    context_seconds: float = 0
    first_progress_seconds: float | None = None
    first_report_seconds: float | None = None
    scout_run_id: str | None = None


def prepare_scout(context: CustomPromptSandboxContext) -> str:
    team = Team.objects.select_related("organization").get(id=context.team_id)
    user = User.objects.get(id=context.user_id)
    team.organization.is_ai_data_processing_approved = True
    team.organization.save(update_fields=["is_ai_data_processing_approved"])
    SignalTeamConfig.objects.update_or_create(team_id=team.id, defaults={"autostart_enabled": False})
    SignalScoutConfig.objects.for_team(team.id).create(
        team_id=team.id,
        skill_name=FIRST_REPORT_SCOUT,
        enabled=False,
        emit=True,
        created_by=user,
        enabled_by=user,
        write_scopes=[],
    )
    SignalSourceConfig.objects.get_or_create(
        team_id=team.id,
        source_product="signals_scout",
        source_type="cross_source_issue",
        defaults={"enabled": True},
    )
    compute_project_profile(team=team, force=True, defer_surfaces=True)
    inventory = build_first_report_context(team, user)
    if not inventory.has_data():
        raise RuntimeError("A scout eval fixture must have queryable data before launching the agent")
    return inventory.prompt_context()


def latest_scout_task(team_id: int) -> TaskRunDTO | None:
    run = SignalScoutRun.objects.for_team(team_id).filter(skill_name=FIRST_REPORT_SCOUT).order_by("-created_at").first()
    return tasks_api.get_task_run(run.task_run_id, team_id=team_id) if run is not None else None


def collect_closeout(team_id: int, run_id: str | None) -> FirstReportScoutResult | None:
    if run_id is None:
        return None
    metadata = (
        SignalScoutRun.objects.for_team(team_id).filter(id=run_id).values_list("metadata", flat=True).first() or {}
    )
    result = metadata.get("first_report_result")
    return FirstReportScoutResult.model_validate(result) if result else None


def collect_reports(team_id: int, started_at: datetime) -> list[EvalReport]:
    return [
        EvalReport(
            id=str(report.id),
            title=report.title or "",
            summary=report.summary or "",
            status=report.status,
            visible_after_seconds=(report.first_visible_at - started_at).total_seconds()
            if report.first_visible_at
            else None,
        )
        for report in SignalReport.objects.filter(team_id=team_id, created_at__gte=started_at)
    ]


def first_progress_seconds(raw_log: str, started_at: datetime) -> float | None:
    for line in raw_log.splitlines():
        try:
            entry = json.loads(line)
            update = entry.get("notification", {}).get("params", {}).get("update", {})
            content = update.get("content", {})
            if (
                update.get("sessionUpdate") in ("agent_message", "agent_message_chunk")
                and content.get("type") == "text"
                and content.get("text", "").strip()
            ):
                timestamp = datetime.fromisoformat(entry["timestamp"])
                return max(0, (timestamp - started_at).total_seconds())
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
    return None


async def finish_scout_eval(
    team_id: int,
    task_run: TaskRunDTO | None,
    *,
    successful: bool,
    provider: SandboxProviderStrategy,
    on_cleanup: Callable[[], Awaitable[None]] | None,
) -> None:
    task_run = task_run or await asyncio.to_thread(latest_scout_task, team_id)
    await _report_cleanup(on_cleanup)
    if task_run is None:
        return
    provider.register_task(str(task_run.task_id))
    try:
        client = await async_connect()
        handle = client.get_workflow_handle(task_run.workflow_id)
        if not await _finish_workflow(
            handle,
            status="completed" if successful else "failed",
            reason=None if successful else "Scout eval interrupted",
        ):
            if successful:
                raise WorkflowCleanupError("Scout eval workflow cleanup could not be confirmed")
            logger.warning("Could not confirm interrupted scout eval workflow cleanup")
    except Exception:
        if successful:
            raise
        logger.warning("Could not finish interrupted scout eval workflow", exc_info=True)
    finally:
        try:
            await asyncio.to_thread(provider.cleanup_case, str(task_run.task_id))
        except Exception:
            if successful:
                raise
            logger.warning("Could not sweep interrupted scout eval sandbox", exc_info=True)


async def run_first_report_scout(
    case: SandboxedEvalCase,
    context: CustomPromptSandboxContext,
    *,
    provider: SandboxProviderStrategy,
    on_cleanup: Callable[[], Awaitable[None]] | None = None,
    timeout_seconds: float | None = None,
    on_poll_timeout: Callable[[TurnPollTimeout], None] | None = None,
) -> EvalCaseResult:
    if case.followups:
        raise ValueError("The first-report scout is a single investigation and cannot accept eval followups")
    if context.sandbox_environment_id is not None or case.interaction_origin is not None:
        raise ValueError("Scout evals use the production environment and interaction origin")
    started_at = timezone.now()
    started = time.monotonic()
    run_note = await asyncio.to_thread(prepare_scout, context)
    context_seconds = time.monotonic() - started
    task_run: TaskRunDTO | None = None
    successful = False
    run = asyncio.create_task(
        arun_signals_scout(
            team_id=context.team_id,
            skill_name=FIRST_REPORT_SCOUT,
            triggered_by=TRIGGERED_BY_ONBOARDING,
            run_note=run_note,
            agent_runtime=AgentRuntime(
                runtime_adapter=context.runtime_adapter, model=context.model, reasoning_effort=context.reasoning_effort
            ),
        )
    )
    try:
        while not run.done() and task_run is None:
            task_run = await asyncio.to_thread(latest_scout_task, context.team_id)
            if task_run is not None:
                provider.register_task(str(task_run.task_id))
            else:
                await asyncio.wait({run}, timeout=1)
        result = await run
        task_run = task_run or await asyncio.to_thread(latest_scout_task, context.team_id)
        if task_run is None:
            raise RuntimeError(f"Scout did not start: {result.skip_reason or result.status}")
        raw_log = (
            await asyncio.to_thread(
                tasks_api.read_task_run_conversation_logs, task_run.id, task_run.task_id, context.team_id
            )
            or ""
        )
        successful = result.status == "completed"
        parsed = _parse_artifacts_from_log(raw_log, time.monotonic() - started, agent_finished=successful)
        outcome = await asyncio.to_thread(first_report_state, context.team_id)
        closeout = await asyncio.to_thread(collect_closeout, context.team_id, result.run_id)
        reports = await asyncio.to_thread(collect_reports, context.team_id, started_at)
        visible = [
            report.visible_after_seconds
            for report in reports
            if report.status in ("ready", "pending_input") and report.visible_after_seconds is not None
        ]
        artifacts = ScoutArtifacts.model_validate(
            {
                **parsed.model_dump(),
                "reports": reports,
                "last_message": result.last_message,
                "scout_closeout": result.last_message,
                "outcome": outcome.get("status", "incomplete"),
                "missing_data": closeout.missing_data if closeout else [],
                "checked_products": closeout.checked_products if closeout else [],
                "context_seconds": context_seconds,
                "first_progress_seconds": first_progress_seconds(raw_log, started_at),
                "first_report_seconds": min(visible) if visible else None,
                "scout_run_id": result.run_id,
            }
        )
        if not successful:
            artifacts.exit_code = 1
            artifacts.stderr = result.last_message or "Scout investigation failed"
        return EvalCaseResult(artifacts=artifacts, raw_log=raw_log, trace_id=str(task_run.id))
    finally:
        if not run.done():
            run.cancel()
            await asyncio.gather(run, return_exceptions=True)
        completion_task = asyncio.create_task(
            finish_scout_eval(
                context.team_id, task_run, successful=successful, provider=provider, on_cleanup=on_cleanup
            )
        )
        try:
            await asyncio.shield(completion_task)
        except asyncio.CancelledError:
            try:
                await asyncio.shield(completion_task)
            except Exception:
                logger.warning("Could not finish cancelled scout eval cleanup", exc_info=True)
            raise
