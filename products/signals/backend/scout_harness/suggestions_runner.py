"""The headless run behind pre-computed scout suggestions: one team, one task, one batch.

Split from `suggestions.py` because this is the only piece that needs the tasks agent facade
(`MultiTurnSession`), which is heavy by import; the planner, contract, and persistence stay light
for the HTTP surface and the config receivers.
"""

from __future__ import annotations

import time
from typing import Literal

import structlog
import posthoganalytics
from rest_framework import serializers

from posthog.dataclasses import frozen
from posthog.event_usage import groups
from posthog.models.team.team import Team
from posthog.sync import database_sync_to_async

from products.signals.backend.agent_runtime import STEP_SCOUT_SUGGESTIONS, resolve_agent_runtime
from products.signals.backend.quota import is_team_signals_quota_limited
from products.signals.backend.sandbox import (
    SIGNALS_REPORT_RESEARCH_ENV_NAME,
    get_or_create_signals_sandbox_env,
    resolve_acting_user_id_for_team,
)
from products.signals.backend.scout_harness.config_registry import (
    MAX_RUN_INTERVAL_MINUTES,
    MIN_RUN_INTERVAL_MINUTES,
    cron_schedule_error,
)
from products.signals.backend.scout_harness.skill_loader import SIGNALS_SCOUT_SKILL_PREFIX
from products.signals.backend.scout_harness.suggestions import (
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
) -> list[ScoutSuggestionItem]:
    """Drop any item the Create action could not apply as-is: unknown canonical names, custom
    drafts with a bad slug or empty body, invalid schedules, duplicates, already-enabled scouts.
    The one-click Create must never fail on a stored suggestion, so invalid ones are not shown."""
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
            if name in canonical_names or not _valid_custom_name(name):
                continue
            if (
                not item.draft_body.strip()
                or len(item.draft_body) > MAX_DRAFT_BODY_CHARS
                or not item.description.strip()
            ):
                continue
        config = item.proposed_config
        if config.run_cron_schedule and not _valid_cron(config.run_cron_schedule):
            continue
        if config.run_interval_minutes is not None and not (
            MIN_RUN_INTERVAL_MINUTES <= config.run_interval_minutes <= MAX_RUN_INTERVAL_MINUTES
        ):
            continue
        if not item.title.strip() or not item.why_here.strip():
            continue
        seen.add(name)
        kept.append(item.model_copy(update={"skill_name": name}))
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
    if team.organization.is_ai_data_processing_approved is not True:
        return "ai_data_processing_not_approved"
    if is_team_signals_quota_limited(team.api_token):
        return "quota_limited"
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
) -> SuggestionRunResult:
    """Generate one team's suggestion batch: gate, mint the headless task, validate, persist.

    Never raises for a failed generation: the row is marked failed (feeding the breaker) and the
    result says so, mirroring the scout runner's fail-safe posture so one bad project cannot take
    a coordinator tick down with it.
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
    user_id = await database_sync_to_async(resolve_acting_user_id_for_team, thread_sensitive=False)(team.id)
    if user_id is None:
        return _finish("skipped", skip_reason="no_active_user")

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
        model=runtime.model,
        runtime_adapter=runtime.runtime_adapter,
        reasoning_effort=runtime.reasoning_effort,
    )
    task_run_id: str | None = None
    try:
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
        await session.end()
    except Exception as error:
        logger.warning("scout_suggestions: generation failed", team_id=team.id, error=str(error), exc_info=True)
        await database_sync_to_async(mark_generation_failed, thread_sensitive=False)(team.id, task_run_id=task_run_id)
        return _finish("failed", task_run_id=task_run_id)

    canonical_names = {name for name, _ in fleet.available_canonical} | set(fleet.enabled_skill_names)
    items = validate_suggestion_items(
        batch.suggestions,
        enabled_skill_names=set(fleet.enabled_skill_names),
        canonical_names=canonical_names,
    )
    await database_sync_to_async(persist_suggestion_batch, thread_sensitive=False)(
        team.id,
        items,
        task_run_id=task_run_id,
        model=runtime.model,
        fleet_snapshot=list(fleet.enabled_skill_names),
    )
    return _finish("completed", task_run_id=task_run_id, suggestion_count=len(items))


__all__ = ["SuggestionRunResult", "arun_scout_suggestions", "validate_suggestion_items"]
