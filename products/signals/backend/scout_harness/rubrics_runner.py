from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from uuid import uuid4

from django.db.models.functions import Substr
from django.utils import timezone

import structlog
from pydantic import JsonValue

from posthog.models.team.team import Team
from posthog.sync import database_sync_to_async

from products.signals.backend.agent_runtime import STEP_SCOUT_RUBRICS, resolve_agent_runtime
from products.signals.backend.models import SignalScoutConfig, SignalScoutRun
from products.signals.backend.rubrics_generation import (
    RUBRIC_FORMAT_CORRECTION_PROMPT as RUBRIC_FORMAT_CORRECTION_PROMPT,
    RUBRIC_GENERATION_PROMPT as RUBRIC_GENERATION_PROMPT,
    RUBRIC_SELECTION_FORMAT_CORRECTION_PROMPT as RUBRIC_SELECTION_FORMAT_CORRECTION_PROMPT,
    RUBRIC_SELECTION_PROMPT as RUBRIC_SELECTION_PROMPT,
    RubricSelection as RubricSelection,
    build_generation_prompt,
    build_selection_prompt as build_selection_prompt,
    generate_rubric,
    read_draft_output as read_draft_output,
    read_selection_output as read_selection_output,
)
from products.signals.backend.scout_harness.prompt import report_disposition_instructions
from products.signals.backend.scout_harness.rubrics import (
    RUBRIC_TEAM_ID,
    ScoutRubricCriterion,
    ScoutRubricGenerationStatus,
    ScoutRubricSource,
    fail_generation,
    read_rubric_state,
    update_generation,
)
from products.signals.backend.scout_harness.skill_loader import load_skill_for_run, resolve_report_channel_variant
from products.signals.backend.temporal.agentic import (
    SIGNALS_REPORT_RESEARCH_ENV_NAME,
    get_or_create_signals_sandbox_env,
)
from products.skills.backend.models.skills import LLMSkillFile
from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.facade.agents import CustomPromptSandboxContext, MultiTurnSession

if TYPE_CHECKING:
    from products.tasks.backend.models import TaskRun

logger = structlog.get_logger(__name__)
MAX_RUNTIME_SECONDS = 15 * 60


def build_rubric_prompt(team: Team, config: SignalScoutConfig) -> str:
    skill = load_skill_for_run(team, config.skill_name)
    report_channel = resolve_report_channel_variant(skill.allowed_tools)
    runs = list(
        SignalScoutRun.objects.for_team(team.id)
        .filter(skill_name=config.skill_name)
        .select_related("task_run")
        .order_by("-created_at")[:5]
    )
    context: dict[str, JsonValue] = {
        "skill_name": skill.name,
        "skill_version": skill.version,
        "description": skill.description,
        "report_channel": report_channel,
        "report_disposition_instructions": report_disposition_instructions(report_channel),
        "instructions": skill.body[:60_000],
        "instructions_truncated": len(skill.body) > 60_000,
        "reference_files": [file.path for file in skill.files[:20]],
        "reference_files_truncated": len(skill.files) > 20,
        "recent_runs": [
            {
                "run_id": str(run.id),
                "task_id": str(run.task_run.task_id),
                "task_run_id": str(run.task_run_id),
                "skill_version": run.skill_version,
                "summary": run.summary[:3000],
                "summary_truncated": len(run.summary) > 3000,
                "status": run.task_run.status,
                "emitted_report_ids": list(run.emitted_report_ids or [])[:5],
                "emitted_report_ids_truncated": len(run.emitted_report_ids or []) > 5,
            }
            for run in runs
        ],
        "saved_criteria": [
            item.model_dump(mode="json")
            for item in read_rubric_state(config).criteria
            if not (item.source == ScoutRubricSource.CUSTOM and item.enabled)
        ],
    }
    remaining_characters = 60_000
    references: list[JsonValue] = []
    truncated_references: list[JsonValue] = []
    files = (
        LLMSkillFile.objects.filter(skill_id=skill.skill_id, skill__team_id=team.id)
        .annotate(snippet=Substr("content", 1, remaining_characters + 1))
        .order_by("path")
        .values("path", "content_type", "snippet")[:4]
    )
    for file in files:
        if remaining_characters == 0:
            break
        content = file["snippet"]
        included = content[:remaining_characters]
        references.append({"path": file["path"], "content_type": file["content_type"], "content": included})
        if len(content) > remaining_characters:
            truncated_references.append(file["path"])
        remaining_characters -= len(included)
    source_bundle: dict[str, JsonValue] = {
        "scout_context": context,
        "reference_texts": references,
        "reference_limits": {
            "omitted_files": len(skill.files) - len(references),
            "truncated_files": truncated_references,
        },
        "history_evidence_scope": (
            "Only the supplied run records and summaries are provided here. Historical task transcripts "
            "and report contents were not inspected or supplied to this generation."
        ),
    }
    return build_generation_prompt(source_bundle)


async def run_rubric_generation(team_id: int, config_id: str, generation_id: str, user_id: int) -> None:
    session: MultiTurnSession | None = None
    completed = False
    format_correction_attempted = False
    try:
        team = await database_sync_to_async(
            lambda: Team.objects.select_related("organization").get(id=team_id), thread_sensitive=True
        )()
        if team.id != RUBRIC_TEAM_ID or team.organization.is_ai_data_processing_approved is not True:
            raise ValueError("Rubric generation is not available for this project")
        allowed = await database_sync_to_async(
            lambda: team.all_users_with_access().filter(id=user_id, is_active=True, is_staff=True).exists(),
            thread_sensitive=True,
        )()
        if not allowed:
            raise ValueError("The requesting user no longer has access")
        config = await database_sync_to_async(
            lambda: SignalScoutConfig.objects.for_team(team_id).get(id=config_id), thread_sensitive=True
        )()
        generation = read_rubric_state(config).generation
        if (
            generation is None
            or generation.id != generation_id
            or generation.status != ScoutRubricGenerationStatus.QUEUED
        ):
            return
        prompt = await database_sync_to_async(build_rubric_prompt, thread_sensitive=True)(team, config)
        sandbox_env_id = await database_sync_to_async(get_or_create_signals_sandbox_env, thread_sensitive=True)(
            team.id, SIGNALS_REPORT_RESEARCH_ENV_NAME, tasks_facade.SandboxNetworkAccessLevel.TRUSTED
        )
        runtime = await database_sync_to_async(resolve_agent_runtime, thread_sensitive=True)(
            team.id, STEP_SCOUT_RUBRICS
        )
        context = CustomPromptSandboxContext(
            team_id=team.id,
            user_id=user_id,
            repository=None,
            sandbox_environment_id=sandbox_env_id,
            posthog_mcp_scopes=[],
            github_read_access=False,
            model=runtime.model,
            runtime_adapter=runtime.runtime_adapter,
            reasoning_effort=runtime.reasoning_effort,
            service_tier=runtime.service_tier,
            initial_permission_mode="full-access" if runtime.runtime_adapter == "codex" else "bypassPermissions",
            sandbox_timeout_seconds=MAX_RUNTIME_SECONDS + 120,
        )

        async def link_task(task_run: TaskRun) -> None:
            generation.task_id = str(task_run.task_id)
            generation.task_run_id = str(task_run.id)
            generation.status = ScoutRubricGenerationStatus.RUNNING
            linked = await database_sync_to_async(update_generation, thread_sensitive=True)(
                team_id, config_id, generation
            )
            if not linked:
                raise ValueError("Generation was replaced before the agent started")

        async def send_prompt(turn_prompt: str, phase: str) -> str:
            nonlocal session, format_correction_attempted
            if phase == "rubric_format_correction":
                format_correction_attempted = True
                logger.info("scout_rubrics_format_correction_requested", config_id=config_id)
            if session is None:
                session, output = await MultiTurnSession.start_raw(
                    prompt=turn_prompt,
                    context=context,
                    step_name="scout_rubrics",
                    # Reuse the suggestions origin's inference routing for this internal session.
                    origin_product=tasks_facade.TaskOriginProduct.SIGNALS_SCOUT_SUGGESTIONS,
                    internal=True,
                    mcp_builtin_agent_key="scout",
                    mcp_gateway_server_ids=[],
                    ai_stage="scout_suggestions",
                    on_task_run_created=link_task,
                    max_poll_seconds=MAX_RUNTIME_SECONDS,
                )
                return output
            return await session.send_followup_raw(turn_prompt, label=phase)

        async def load_saved_criteria() -> list[ScoutRubricCriterion]:
            # Read the config again because the owner can save rubric edits while the draft turn runs.
            saved_config = await database_sync_to_async(
                lambda: SignalScoutConfig.objects.for_team(team_id).get(id=config_id), thread_sensitive=True
            )()
            return read_rubric_state(saved_config).criteria

        async with asyncio.timeout(MAX_RUNTIME_SECONDS + 60):
            result = await generate_rubric(prompt, send_prompt=send_prompt, load_saved_criteria=load_saved_criteria)
            batch = result.batch
            if result.format_correction_attempted:
                logger.info("scout_rubrics_format_correction_completed", config_id=config_id)
        generation.status = ScoutRubricGenerationStatus.COMPLETED
        generation.completed_at = timezone.now()
        generation.summary = batch.summary
        generation.suggestions = [
            ScoutRubricCriterion(
                id=f"custom-{uuid4()}",
                **suggestion.model_dump(),
                enabled=True,
                source=ScoutRubricSource.CUSTOM,
            )
            for suggestion in batch.suggestions
        ]
        await database_sync_to_async(update_generation, thread_sensitive=True)(team_id, config_id, generation)
        completed = True
    except (Exception, asyncio.CancelledError) as error:
        logger.warning(
            "scout_rubrics_generation_failed",
            config_id=config_id,
            error_type=type(error).__name__,
            format_correction_attempted=format_correction_attempted,
        )
        await asyncio.shield(
            database_sync_to_async(fail_generation, thread_sensitive=True)(
                team_id,
                config_id,
                generation_id,
                "Generation did not finish. Try again; your saved rubrics are unchanged.",
            )
        )
        if isinstance(error, asyncio.CancelledError):
            raise
    finally:
        if session is not None:
            try:
                await asyncio.shield(
                    session.end(
                        status="completed" if completed else "failed",
                        error=None if completed else "Rubric generation failed",
                    )
                )
            except Exception as error:
                logger.warning("scout_rubrics_cleanup_failed", config_id=config_id, error_type=type(error).__name__)
