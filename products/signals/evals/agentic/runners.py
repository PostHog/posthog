from __future__ import annotations

import json
import asyncio
import logging
from dataclasses import asdict, replace
from typing import TYPE_CHECKING, Any

from django.core.serializers.json import DjangoJSONEncoder

from pydantic import BaseModel, Field, model_validator

from products.posthog_ai.eval_harness.base import EvalTaskCancelled, EvalTaskError
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.log_parser import LogParser
from products.posthog_ai.eval_harness.runner import parse_agent_artifacts
from products.signals.backend.agent_runtime import AgentRuntime
from products.signals.backend.models import (
    SignalReport,
    SignalReportArtefact,
    SignalScoutConfig,
    SignalScoutRun,
    SignalScratchpad,
)
from products.signals.backend.report_generation.select_repo import RepoSelectionResult
from products.signals.evals.agentic.datasets import ImplementationCase, RepoSelectionCase, ResearchCase, ScoutCase
from products.tasks.backend.facade.agents import CustomPromptSandboxContext, MultiTurnSession
from products.tasks.backend.models import TaskRun

if TYPE_CHECKING:
    from products.signals.backend.scout_harness.runner import RunResult

logger = logging.getLogger(__name__)


def _runtime(ctx: EvalContext) -> AgentRuntime:
    return AgentRuntime(
        runtime_adapter=ctx.agent_runtime,
        model=ctx.agent_model,
        reasoning_effort=ctx.reasoning_effort,
    )


def _context(
    sandbox_context: CustomPromptSandboxContext,
    ctx: EvalContext,
    *,
    repository: str | None,
) -> CustomPromptSandboxContext:
    return replace(
        sandbox_context,
        repository=repository,
        posthog_mcp_scopes="read_only",
        model=ctx.agent_model,
        runtime_adapter=ctx.agent_runtime,
        reasoning_effort=ctx.reasoning_effort,
        initial_permission_mode="full-access" if ctx.agent_runtime == "codex" else "bypassPermissions",
    )


async def _read_task_logs(team_id: int, task_id: str, run_id: str | None = None) -> str:
    from products.tasks.backend.facade import api as tasks_facade
    from products.tasks.backend.models import TaskRun

    if run_id is None:
        run_id = await asyncio.to_thread(
            lambda: str(
                TaskRun.objects.filter(team_id=team_id, task_id=task_id)
                .order_by("-created_at")
                .values_list("id", flat=True)
                .first()
                or ""
            )
        )
    if not run_id:
        return ""
    return (await asyncio.to_thread(tasks_facade.read_task_run_logs, run_id, task_id, team_id)) or ""


async def run_research(
    case: ResearchCase,
    sandbox_context: CustomPromptSandboxContext,
    ctx: EvalContext,
) -> dict[str, Any]:
    from products.signals.backend.report_generation.research import run_multi_turn_research

    result = await run_multi_turn_research(
        [signal.to_signal_data() for signal in case.signals],
        _context(sandbox_context, ctx, repository=case.repo),
        title=case.title,
        summary=case.summary,
        signal_report_id=None,
        verbose=True,
        output_fn=lambda message: logger.info("research[%s]: %s", case.case_id, message),
    )
    output = result.model_dump(mode="json")
    if result.research_task_id:
        output["raw_log"] = await _read_task_logs(sandbox_context.team_id, result.research_task_id)
    return output


class RepoSelectionOutput(RepoSelectionResult):
    raw_log: str = ""


async def run_repo_selection(
    case: RepoSelectionCase,
    sandbox_context: CustomPromptSandboxContext,
    ctx: EvalContext,
) -> dict[str, Any]:
    from products.signals.backend.report_generation.select_repo import select_repository_for_team
    from products.signals.backend.temporal.types import render_signals_to_text

    request = case.context or render_signals_to_text([signal.to_signal_data() for signal in case.signals])
    result = await select_repository_for_team(
        sandbox_context.team_id,
        sandbox_context.user_id,
        request,
        signal_report_id=None,
        sandbox_environment_id=sandbox_context.sandbox_environment_id,
        verbose=True,
        output_fn=lambda message: logger.info("repo-selection[%s]: %s", case.case_id, message),
        agent_runtime=_runtime(ctx),
    )
    raw_log = ""
    if result.task_id:
        raw_log = await _read_task_logs(sandbox_context.team_id, result.task_id)
    return RepoSelectionOutput(**result.model_dump(), raw_log=raw_log).model_dump(mode="json")


class ImplementationOutput(BaseModel):
    diff: str
    files_changed: list[str] = Field(default_factory=list)
    summary: str = ""
    raw_log: str = ""
    task_id: str | None = None
    task_run_id: str | None = None

    def __init__(self, diff: str | None = None, **data: Any) -> None:
        if diff is not None:
            data["diff"] = diff
        super().__init__(**data)

    @model_validator(mode="after")
    def populate_files_changed(self) -> ImplementationOutput:
        if not self.files_changed:
            self.files_changed = _files_from_diff(self.diff)
        return self


def _files_from_diff(diff: str) -> list[str]:
    files: list[str] = []
    for line in diff.splitlines():
        if not line.startswith("diff --git "):
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        path = parts[3].removeprefix("b/")
        if path not in files:
            files.append(path)
    return files


async def run_implementation(
    case: ImplementationCase,
    sandbox_context: CustomPromptSandboxContext,
    ctx: EvalContext,
) -> dict[str, Any]:
    from products.signals.backend.auto_start import (
        build_implementation_task_description,
        build_implementation_task_prompt,
    )
    from products.signals.evals.agentic.repos import REGISTRY
    from products.tasks.backend.facade import api as tasks_facade

    repository = REGISTRY[case.repo].full_name if case.repo in REGISTRY else case.repo
    prompt = build_implementation_task_prompt(
        build_implementation_task_description(
            report_id=f"eval-{case.case_id}",
            team_id=sandbox_context.team_id,
            summary=case.issue_prompt,
            repository=repository,
            priority=None,
        ),
        f"posthog-self-driving/eval-{case.case_id}",
    )
    session, reported = await MultiTurnSession.start_raw(
        prompt=prompt,
        context=_context(sandbox_context, ctx, repository=repository),
        step_name="implementation",
        origin_product=tasks_facade.TaskOriginProduct.SIGNAL_REPORT,
        ai_stage="implementation",
        internal=True,
        verbose=True,
        output_fn=lambda message: logger.info("implementation[%s]: %s", case.case_id, message),
    )
    try:
        task_id = str(session.task.id)
        task_run_id = str(session.task_run.id)
    finally:
        await asyncio.shield(session.end())
    raw_log = await _read_task_logs(sandbox_context.team_id, task_id, task_run_id)
    diff = parse_agent_artifacts(raw_log, duration_seconds=0, agent_finished=True).git_diff
    return ImplementationOutput(
        diff=diff,
        summary=reported,
        raw_log=raw_log,
        task_id=task_id,
        task_run_id=task_run_id,
    ).model_dump(mode="json")


class ScoutOutput(BaseModel):
    outcome: str
    summary: str
    emitted_report_ids: list[str] = Field(default_factory=list)
    edited_report_ids: list[str] = Field(default_factory=list)
    emitted_finding_ids: list[str] = Field(default_factory=list)
    scratchpad_keys: list[str] = Field(default_factory=list)
    raw_log: str = ""
    run_id: str | None = None
    task_run_id: str | None = None
    artifacts: dict[str, Any] = Field(default_factory=dict)


def _capture_scout_state(team_id: int, skill_name: str) -> dict[str, list[dict[str, Any]]]:
    state = {
        "reports": list(SignalReport.objects.filter(team_id=team_id).order_by("id").values()),
        "report_artefacts": list(
            SignalReportArtefact.objects.filter(team_id=team_id, report__team_id=team_id).order_by("id").values()
        ),
        "scratchpad": list(SignalScratchpad.objects.for_team(team_id).order_by("id").values()),
        "scout_runs": list(
            SignalScoutRun.objects.for_team(team_id).filter(skill_name=skill_name).order_by("created_at", "id").values()
        ),
        "scout_configs": list(
            SignalScoutConfig.objects.for_team(team_id).filter(skill_name=skill_name).order_by("id").values()
        ),
    }
    return json.loads(json.dumps(state, cls=DjangoJSONEncoder))


def _scout_state_changes(
    before: dict[str, list[dict[str, Any]]], after: dict[str, list[dict[str, Any]]]
) -> dict[str, dict[str, list[str]]]:
    changes = {}
    for collection, rows in after.items():
        initial = {str(row["id"]): row for row in before[collection]}
        final = {str(row["id"]): row for row in rows}
        changes[collection] = {
            "created": sorted(final.keys() - initial.keys()),
            "updated": sorted(key for key in initial.keys() & final.keys() if initial[key] != final[key]),
            "deleted": sorted(initial.keys() - final.keys()),
        }
    return changes


def _read_scout_output(
    team_id: int,
    run_id: str,
    previous_scratchpad_keys: set[str],
) -> ScoutOutput:
    run = SignalScoutRun.objects.for_team(team_id).get(id=run_id)
    scratchpad_keys = list(
        SignalScratchpad.objects.for_team(team_id)
        .exclude(key__in=previous_scratchpad_keys)
        .values_list("key", flat=True)
    )
    emitted_report_ids = list(run.emitted_report_ids or [])
    edited_report_ids = list(run.edited_report_ids or [])
    emitted_finding_ids = list(run.emitted_finding_ids or [])
    return ScoutOutput(
        outcome=_scout_outcome(emitted_report_ids, edited_report_ids, emitted_finding_ids, scratchpad_keys),
        summary=run.summary,
        emitted_report_ids=emitted_report_ids,
        edited_report_ids=edited_report_ids,
        emitted_finding_ids=emitted_finding_ids,
        scratchpad_keys=scratchpad_keys,
    )


def _scout_outcome(
    emitted_report_ids: list[str],
    edited_report_ids: list[str],
    emitted_finding_ids: list[str],
    scratchpad_keys: list[str],
) -> str:
    if emitted_report_ids:
        return "emit_report"
    if edited_report_ids:
        return "edit_report"
    if emitted_finding_ids:
        return "emit_signal"
    if scratchpad_keys:
        return "remember"
    return "no_output"


def _remembered_scratchpad_keys(raw_log: str) -> list[str]:
    return [
        key
        for call in LogParser.cached(raw_log).get_tool_calls("scout-scratchpad-remember")
        if not call.is_error and isinstance((key := call.input.get("key")), str)
    ]


async def _collect_scout_output(
    case: ScoutCase,
    sandbox_context: CustomPromptSandboxContext,
    ctx: EvalContext,
    before: dict[str, list[dict[str, Any]]],
    result: RunResult | None = None,
) -> dict[str, Any]:
    after = await asyncio.to_thread(_capture_scout_state, sandbox_context.team_id, case.skill_name)
    artifacts: dict[str, Any] = {
        "before": before,
        "after": after,
        "changes": _scout_state_changes(before, after),
        "requested": {
            "skill_name": case.skill_name,
            "skill_version": case.skill_version,
            "repository": case.repository,
            "run_note": case.run_note,
            "agent_model": ctx.agent_model,
            "agent_runtime": ctx.agent_runtime,
            "reasoning_effort": ctx.reasoning_effort,
        },
        "result": asdict(result) if result is not None else None,
    }
    initial_run_ids = {row["id"] for row in before["scout_runs"]}
    new_runs = [row for row in after["scout_runs"] if row["id"] not in initial_run_ids]
    run_id = result.run_id if result is not None else (new_runs[0]["id"] if len(new_runs) == 1 else None)
    if run_id is None:
        return ScoutOutput(
            outcome="no_output", summary=result.skip_reason or "" if result else "", artifacts=artifacts
        ).model_dump(mode="json")

    previous_keys = {row["key"] for row in before["scratchpad"]}
    output = await asyncio.to_thread(_read_scout_output, sandbox_context.team_id, run_id, previous_keys)
    output.artifacts = artifacts
    output.run_id = run_id
    run_row = next(row for row in after["scout_runs"] if row["id"] == run_id)
    task_run_id = run_row.get("task_run_id")
    output.task_run_id = task_run_id
    provider = ctx.provider_strategy
    task_id: str | None = None
    try:
        if task_run_id:
            task_run = await asyncio.to_thread(
                lambda: (
                    TaskRun.objects.filter(team_id=sandbox_context.team_id, id=task_run_id)
                    .values("id", "task_id", "status", "error_message", "created_at", "completed_at")
                    .get()
                )
            )
            task_id = str(task_run["task_id"])
            if provider is not None:
                provider.register_task(task_id)
            artifacts["task_run"] = json.loads(json.dumps(task_run, cls=DjangoJSONEncoder))
            try:
                output.raw_log = await _read_task_logs(sandbox_context.team_id, task_id, task_run_id)
            except Exception as exc:
                raise EvalTaskError(
                    f"Could not retrieve scout transcript: {exc}", output.model_dump(mode="json")
                ) from exc
        output.scratchpad_keys = sorted(set(output.scratchpad_keys) | set(_remembered_scratchpad_keys(output.raw_log)))
        output.outcome = _scout_outcome(
            output.emitted_report_ids,
            output.edited_report_ids,
            output.emitted_finding_ids,
            output.scratchpad_keys,
        )
        return output.model_dump(mode="json")
    finally:
        if provider is not None and task_id is not None:
            try:
                await asyncio.to_thread(provider.cleanup_case, task_id)
            except Exception:
                logger.warning("Provider cleanup failed for scout task %s", task_id, exc_info=True)


async def run_scout(
    case: ScoutCase,
    sandbox_context: CustomPromptSandboxContext,
    ctx: EvalContext,
) -> dict[str, Any]:
    from products.signals.backend.scout_harness.runner import arun_signals_scout

    before = await asyncio.to_thread(_capture_scout_state, sandbox_context.team_id, case.skill_name)
    try:
        result = await arun_signals_scout(
            team_id=sandbox_context.team_id,
            skill_name=case.skill_name,
            skill_version=case.skill_version,
            repository=case.repository,
            run_note=case.run_note,
            verbose=True,
            triggered_by="manual",
            agent_runtime=_runtime(ctx),
        )
    except asyncio.CancelledError as exc:
        output = await _collect_scout_output(case, sandbox_context, ctx, before)
        raise EvalTaskCancelled("Scout execution cancelled", output) from exc
    except Exception as exc:
        output = await _collect_scout_output(case, sandbox_context, ctx, before)
        raise EvalTaskError(str(exc), output) from exc
    return await _collect_scout_output(case, sandbox_context, ctx, before, result)
