from __future__ import annotations

import re
import asyncio
import logging
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.runner import parse_agent_artifacts
from products.signals.backend.agent_runtime import AgentRuntime
from products.signals.evals.agentic.datasets import ImplementationCase, RepoSelectionCase, ResearchCase, ScoutCase
from products.tasks.backend.facade.agents import CustomPromptSandboxContext, MultiTurnSession

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
    output = result.model_dump(mode="json")
    if result.task_id:
        output["raw_log"] = await _read_task_logs(sandbox_context.team_id, result.task_id)
    return output


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


class _ImplementationResponse(BaseModel):
    diff: str = Field(description="The full unified diff from git diff --cached.")
    summary: str = Field(description="One sentence describing the change.")


def _implementation_prompt(case: ImplementationCase, repository: str) -> str:
    return f"""You are a coding agent. The repository `{repository}` is checked out on disk.

Implement this change with a minimal, focused edit:

{case.issue_prompt}

Do not refactor unrelated code or touch lock files. Run relevant tests when practical. Before responding,
run `git add -A` and `git diff --cached`. Return JSON with the exact full unified diff in `diff` and a
one-sentence `summary`. Do not push or open a pull request."""


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
    from products.signals.evals.agentic.repos import REGISTRY
    from products.tasks.backend.facade import api as tasks_facade

    repository = REGISTRY[case.repo].full_name if case.repo in REGISTRY else case.repo
    session, reported = await MultiTurnSession.start(
        prompt=_implementation_prompt(case, repository),
        context=_context(sandbox_context, ctx, repository=repository),
        model=_ImplementationResponse,
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
        await session.end()
    raw_log = await _read_task_logs(sandbox_context.team_id, task_id, task_run_id)
    artifacts = parse_agent_artifacts(raw_log, duration_seconds=0, agent_finished=True)
    diff = artifacts.git_diff
    return ImplementationOutput(
        diff=diff,
        files_changed=_files_from_diff(diff),
        summary=reported.summary,
        raw_log=raw_log,
        task_id=task_id,
        task_run_id=task_run_id,
    ).model_dump(mode="json")


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, bool | int | float):
        return str(value)
    if isinstance(value, Mapping):
        for key in ("value", "choice", "status", "priority", "actionability", "decision", "summary", "reasoning"):
            if key in value:
                return _string_or_none(value[key])
    if isinstance(value, list | tuple):
        return "; ".join(item for item in (_string_or_none(item) for item in value) if item)
    return str(value)


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list | tuple):
        return [item for item in (_string_or_none(item) for item in value) if item]
    text = _string_or_none(value)
    return [text] if text else []


def _canonical_decision(value: str | None) -> str:
    normalized = (value or "").lower().replace(" ", "_").replace("-", "_")
    for decision in ("emit_report", "edit_report", "remember_only", "close_quiet", "skip"):
        if decision in normalized:
            return decision
    return normalized


def _canonical_actionability(value: str | None) -> str | None:
    normalized = (value or "").lower()
    if not normalized:
        return None
    if "human" in normalized or "input" in normalized:
        return "requires_human_input"
    if "not" in normalized and "action" in normalized:
        return "not_actionable"
    if "action" in normalized:
        return "immediately_actionable"
    return value


def _canonical_priority(value: str | None) -> str | None:
    match = re.search(r"p\s*-?\s*([0-4])", (value or "").lower())
    return f"P{match.group(1)}" if match else None


def _normalize_scout_payload(value: Any) -> Any:
    if not isinstance(value, Mapping):
        return value
    payload = dict(value)
    payload["decision"] = _canonical_decision(_string_or_none(payload.get("decision")))
    payload["summary"] = _string_or_none(payload.get("summary")) or ""
    payload["evidence"] = _string_list(payload.get("evidence"))
    payload["scratchpad_keys"] = _string_list(payload.get("scratchpad_keys"))
    payload["suggested_reviewers"] = _string_list(payload.get("suggested_reviewers"))
    payload["actionability"] = _canonical_actionability(_string_or_none(payload.get("actionability")))
    payload["priority"] = _canonical_priority(_string_or_none(payload.get("priority")))
    payload["existing_report_id"] = _string_or_none(payload.get("existing_report_id"))
    payload["repository"] = _string_or_none(payload.get("repository"))
    return payload


class ScoutDecisionOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    decision: str
    summary: str
    evidence: list[str] = Field(default_factory=list)
    actionability: str | None = None
    priority: str | None = None
    existing_report_id: str | None = None
    scratchpad_keys: list[str] = Field(default_factory=list)
    suggested_reviewers: list[str] = Field(default_factory=list)
    repository: str | None = None
    raw_log: str = ""
    task_id: str | None = None
    task_run_id: str | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_payload(cls, value: Any) -> Any:
        return _normalize_scout_payload(value)


def _scout_prompt(case: ScoutCase) -> str:
    return f"""Evaluate one Signals scout run using this synthetic project brief. Do not call tools.

Scout: {case.scout_name}

Project profile:
{case.project_profile}

Prior context:
{case.prior_context or "No prior context."}

Current observations:
{case.observations}

Candidate reports:
{case.candidate_reports or "No matching reports found."}

Choose exactly one decision: emit_report, edit_report, remember_only, close_quiet, or skip. Be conservative:
duplicate reports and false positives are worse than quiet close-outs. For emit/edit include concrete evidence,
actionability, priority, and grounded summary. For edit or dedupe set existing_report_id. Always include stable,
topical scratchpad_keys. Set repository and suggested_reviewers only when the brief identifies them."""


async def run_scout(
    case: ScoutCase,
    sandbox_context: CustomPromptSandboxContext,
    ctx: EvalContext,
) -> dict[str, Any]:
    from products.tasks.backend.facade import api as tasks_facade

    session, result = await MultiTurnSession.start(
        prompt=_scout_prompt(case),
        context=_context(sandbox_context, ctx, repository=None),
        model=ScoutDecisionOutput,
        step_name="scout",
        origin_product=tasks_facade.TaskOriginProduct.SIGNAL_REPORT,
        ai_stage="scout",
        internal=True,
        verbose=True,
        output_fn=lambda message: logger.info("scout[%s]: %s", case.case_id, message),
    )
    try:
        task_id = str(session.task.id)
        task_run_id = str(session.task_run.id)
    finally:
        await session.end()
    result.raw_log = await _read_task_logs(sandbox_context.team_id, task_id, task_run_id)
    result.task_id = task_id
    result.task_run_id = task_run_id
    return result.model_dump(mode="json")
