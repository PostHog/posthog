"""The headless run behind pre-computed scout suggestions: one team, one task, one batch.

Split from `suggestions.py` because this is the only piece that needs the tasks agent facade
(`MultiTurnSession`), which is heavy by import; the planner, contract, and persistence stay light
for the HTTP surface and the config receivers.
"""

from __future__ import annotations

import time
import asyncio
from collections.abc import Collection
from typing import Literal

import structlog
import posthoganalytics
from rest_framework import serializers

from posthog.dataclasses import frozen
from posthog.event_usage import groups
from posthog.models.team.team import Team
from posthog.sync import database_sync_to_async

from products.signals.backend.agent_runtime import STEP_SCOUT_SUGGESTIONS, resolve_agent_runtime
from products.signals.backend.scout_harness.config_registry import (
    MAX_RUN_INTERVAL_MINUTES,
    MIN_RUN_INTERVAL_MINUTES,
    cron_schedule_error,
)
from products.signals.backend.scout_harness.skill_loader import SIGNALS_SCOUT_SKILL_PREFIX
from products.signals.backend.scout_harness.suggestions import (
    MAX_DESCRIPTION_CHARS,
    MAX_DRAFT_BODY_CHARS,
    MAX_SUGGESTIONS_PER_BATCH,
    SUGGESTIONS_AI_STAGE,
    ScoutSuggestionBatch,
    ScoutSuggestionItem,
    SuggestionSettings,
    build_suggestions_prompt,
    fleet_context,
    mark_generation_failed,
    persist_suggestion_batch,
)
from products.signals.backend.temporal.agentic import (
    SIGNALS_REPORT_RESEARCH_ENV_NAME,
    get_or_create_signals_sandbox_env,
    resolve_acting_user_id_for_team,
)
from products.skills.backend.api.skill_serializers import validate_skill_name_value
from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.facade.agents import CustomPromptSandboxContext, MultiTurnSession

logger = structlog.get_logger(__name__)


def _valid_cron(expression: str) -> bool:
    # The same rule the scout create API applies, so a stored schedule can never fail on create.
    return cron_schedule_error(expression) is None


def _valid_custom_name(name: str) -> bool:
    if not name.startswith(SIGNALS_SCOUT_SKILL_PREFIX):
        return False
    try:
        validate_skill_name_value(name)
    except serializers.ValidationError:
        return False
    return True


def validate_suggestion_items(
    items: list[ScoutSuggestionItem],
    *,
    enabled_skill_names: set[str],
    canonical_names: set[str],
    reserved_names: Collection[str] = (),
) -> list[ScoutSuggestionItem]:
    """Drop any item the Create action could not apply as-is: unknown canonical names, custom
    drafts with a bad slug, empty body, or a name the project already holds (a disabled config or
    a stored skill, which create answers with 409), invalid schedules, duplicates, already-enabled
    scouts. The one-click Create must never fail on a stored suggestion, so invalid ones are not
    shown."""
    seen: set[str] = set()
    kept: list[ScoutSuggestionItem] = []
    for item in items:
        name = item.skill_name.strip()
        if not name or name in seen or name in enabled_skill_names:
            continue
        if item.kind == "canonical":
            if name not in canonical_names:
                continue
        else:
            if name in canonical_names or name in reserved_names or not _valid_custom_name(name):
                continue
            if (
                not item.draft_body.strip()
                or len(item.draft_body) > MAX_DRAFT_BODY_CHARS
                or not item.description.strip()
                or len(item.description) > MAX_DESCRIPTION_CHARS
            ):
                continue
        config = item.proposed_config
        # The create serializers accept a null cron but not a blank one, so a blank normalizes.
        cron = (config.run_cron_schedule or "").strip() or None
        if cron is not None and not _valid_cron(cron):
            continue
        if config.run_interval_minutes is not None and not (
            MIN_RUN_INTERVAL_MINUTES <= config.run_interval_minutes <= MAX_RUN_INTERVAL_MINUTES
        ):
            continue
        if not item.title.strip() or not item.why_here.strip():
            continue
        seen.add(name)
        kept.append(
            item.model_copy(
                update={"skill_name": name, "proposed_config": config.model_copy(update={"run_cron_schedule": cron})}
            )
        )
        if len(kept) == MAX_SUGGESTIONS_PER_BATCH:
            break
    return kept


@frozen
class SuggestionRunResult:
    team_id: int
    status: Literal["completed", "failed", "skipped"]
    task_run_id: str | None
    suggestion_count: int
    runtime_s: float
    skip_reason: str | None = None


def _gate_skip_reason(team: Team) -> str | None:
    """No self-driving credits gate here: a scan opens no pull request, so it bills nothing, and
    the coordinator stamps `last_requested_at` at dispatch — a skip would cost the team its whole
    refresh window for a limit the scan never charges against.
    """
    if team.organization.is_ai_data_processing_approved is not True:
        return "ai_data_processing_not_approved"
    return None


def _capture_generated(
    team: Team, *, result: SuggestionRunResult, tier: int | None, model: str | None, triggered_by: str
) -> None:
    try:
        posthoganalytics.capture(
            event="$scout_suggestions_generated",
            distinct_id=str(team.uuid),
            properties={
                "team_id": team.id,
                "status": result.status,
                "skip_reason": result.skip_reason,
                "suggestion_count": result.suggestion_count,
                "runtime_s": round(result.runtime_s, 1),
                "task_run_id": result.task_run_id,
                "tier": tier,
                "model": model,
                "triggered_by": triggered_by,
            },
            groups=groups(team.organization, team),
        )
    except Exception:
        logger.warning("scout_suggestions: failed to capture generated event", team_id=team.id)


async def arun_scout_suggestions(
    team_id: int,
    *,
    settings: SuggestionSettings | None = None,
    tier: int | None = None,
    triggered_by: str = "schedule",
    acting_user_id: int | None = None,
) -> SuggestionRunResult:
    """Generate one team's suggestion batch: gate, mint the headless task, validate, persist.

    Never raises for a failed generation: anything after the gates (fleet discovery, sandbox and
    runtime resolution, the run, validation, persistence) marks the row failed, feeding the
    breaker, and the result says so. This mirrors the scout runner's fail-safe posture so one
    bad project cannot take a coordinator tick down with it, and so a failure before the run
    still counts: the coordinator has already stamped the team for a full refresh window.
    """
    started = time.monotonic()
    settings = settings or SuggestionSettings()
    team = await database_sync_to_async(
        lambda: Team.objects.select_related("organization").get(id=team_id), thread_sensitive=False
    )()
    model: str | None = None

    def _finish(
        status: Literal["completed", "failed", "skipped"],
        *,
        task_run_id: str | None = None,
        suggestion_count: int = 0,
        skip_reason: str | None = None,
    ) -> SuggestionRunResult:
        result = SuggestionRunResult(
            team_id=team_id,
            status=status,
            task_run_id=task_run_id,
            suggestion_count=suggestion_count,
            runtime_s=time.monotonic() - started,
            skip_reason=skip_reason,
        )
        _capture_generated(team, result=result, tier=tier, model=model, triggered_by=triggered_by)
        return result

    skip_reason = await database_sync_to_async(_gate_skip_reason, thread_sensitive=False)(team)
    if skip_reason is not None:
        return _finish("skipped", skip_reason=skip_reason)
    # A manual refresh runs as its authenticated caller, so the batch is minted under that
    # caller's own access rather than a possibly more privileged resolved member.
    user_id = acting_user_id
    if user_id is None:
        user_id = await database_sync_to_async(resolve_acting_user_id_for_team, thread_sensitive=False)(team.id)
    if user_id is None:
        return _finish("skipped", skip_reason="no_active_user")

    task_run_id: str | None = None
    session: MultiTurnSession | None = None
    try:
        fleet = await database_sync_to_async(fleet_context, thread_sensitive=False)(team.id)
        sandbox_env_id = await database_sync_to_async(get_or_create_signals_sandbox_env, thread_sensitive=False)(
            team.id, SIGNALS_REPORT_RESEARCH_ENV_NAME, tasks_facade.SandboxNetworkAccessLevel.TRUSTED
        )
        runtime = await database_sync_to_async(resolve_agent_runtime, thread_sensitive=False)(
            team.id, STEP_SCOUT_SUGGESTIONS
        )
        model = runtime.model
        context = CustomPromptSandboxContext(
            team_id=team.id,
            user_id=user_id,
            repository=None,
            sandbox_environment_id=sandbox_env_id,
            # Reads only: the scan never writes, and `read_only` still carries `llm_skill:read` for
            # the authoring-scouts skill and `signal_scout:read` for the fleet and recent runs.
            posthog_mcp_scopes="read_only",
            # No GitHub at all: `Task._build_task` leaves this origin's `github_integration`
            # unset, so no token is minted. The scan grounds itself in project data a member can
            # write, and a repository token would let planted text pull private source into a
            # suggestion field the API hands back.
            github_read_access=False,
            model=runtime.model,
            runtime_adapter=runtime.runtime_adapter,
            reasoning_effort=runtime.reasoning_effort,
        )
        session, batch = await MultiTurnSession.start(
            prompt=build_suggestions_prompt(fleet),
            context=context,
            model=ScoutSuggestionBatch,
            step_name="scout_suggestions",
            origin_product=tasks_facade.TaskOriginProduct.SIGNALS_SCOUT_SUGGESTIONS,
            # Not a user's task: hidden from the task tracker and never mounts personal MCP grants.
            internal=True,
            # Runs as the Scout agent with an empty server allowlist, so nothing from the MCP Store
            # is mounted; the scan needs only the PostHog MCP.
            mcp_builtin_agent_key="scout",
            mcp_gateway_server_ids=[],
            ai_stage=SUGGESTIONS_AI_STAGE,
            max_poll_seconds=settings.max_runtime_s,
            # No prose salvage: an unparseable close-out is a failed generation, since no human is
            # there to repair it and the Create action needs the structured draft.
            fallback_from_text=None,
        )
        task_run_id = str(session.task_run.id)

        canonical_names = {name for name, _ in fleet.available_canonical} | set(fleet.enabled_skill_names)
        items = validate_suggestion_items(
            batch.suggestions,
            enabled_skill_names=set(fleet.enabled_skill_names),
            canonical_names=canonical_names,
            reserved_names=fleet.reserved_names,
        )
        if batch.suggestions and not items:
            # The model produced only unusable output. Persisting that as an empty success would
            # reset the breaker and buy it a whole refresh window on the strength of nothing.
            raise ValueError(f"every suggestion in a batch of {len(batch.suggestions)} failed validation")
        await database_sync_to_async(persist_suggestion_batch, thread_sensitive=False)(
            team.id,
            items,
            task_run_id=task_run_id,
            model=runtime.model,
            fleet_snapshot=list(fleet.enabled_skill_names),
        )
        # The TaskRun closes as completed only once the batch is stored: its terminal status is
        # what run metrics and triage read, and a scan whose output never landed did fail.
        await session.end()
    except asyncio.CancelledError:
        # The activity deadline cancels the coroutine with a BaseException, which the handler
        # below would not see. The coordinator has already stamped `last_requested_at`, so an
        # unrecorded cancellation would suppress the project for a whole refresh window.
        logger.warning("scout_suggestions: generation cancelled", team_id=team.id, exc_info=True)
        await _end_failed(session, "cancelled")
        await database_sync_to_async(mark_generation_failed, thread_sensitive=False)(team.id, task_run_id=task_run_id)
        raise
    except Exception as error:
        logger.warning("scout_suggestions: generation failed", team_id=team.id, error=str(error), exc_info=True)
        await _end_failed(session, str(error))
        await database_sync_to_async(mark_generation_failed, thread_sensitive=False)(team.id, task_run_id=task_run_id)
        return _finish("failed", task_run_id=task_run_id)
    return _finish("completed", task_run_id=task_run_id, suggestion_count=len(items))


async def _end_failed(session: MultiTurnSession | None, error: str) -> None:
    if session is None:
        return
    # Shielded so the failure status still lands when a cancel re-fires mid-signal.
    await asyncio.shield(session.end(status="failed", error=error))


__all__ = ["SuggestionRunResult", "arun_scout_suggestions", "validate_suggestion_items"]
