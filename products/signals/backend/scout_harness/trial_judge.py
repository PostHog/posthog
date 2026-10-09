from __future__ import annotations

import json
import asyncio
from dataclasses import field
from datetime import timedelta
from uuid import UUID, uuid5

from django.db import IntegrityError
from django.utils import timezone

from pydantic import JsonValue

from posthog.clickhouse.query_tagging import private_capture_context
from posthog.dataclasses import frozen
from posthog.models import Team
from posthog.sync import database_sync_to_async

from products.signals.backend import trial_judging
from products.signals.backend.models import SignalScoutRun
from products.signals.backend.scout_harness.trial_evaluation import (
    TrialEvaluationError,
    read_trial_evidence_sources,
    trial_evidence_storage_key,
)
from products.signals.backend.scout_harness.trial_evaluation_types import TrialEvaluationSnapshot
from products.signals.backend.scout_harness.trial_launch import (
    assert_trial_environment_ready,
    assert_trial_work_enabled,
)
from products.signals.backend.scout_harness.trial_state import ScoutTrialStore
from products.signals.backend.temporal.agentic import get_or_create_signals_sandbox_env
from products.signals.backend.trial_judging import (
    JUDGE_PROMPT_VERSION as JUDGE_PROMPT_VERSION,
    MAX_JUDGE_OUTPUT_CHARACTERS as MAX_JUDGE_OUTPUT_CHARACTERS,
    TrialJudgeExecutionError as TrialJudgeExecutionError,
    TrialJudgeInput,
    TrialJudgeValidationError as TrialJudgeValidationError,
    parse_trial_judgment as parse_trial_judgment,
    safe_judge_failure as safe_judge_failure,
)
from products.signals.backend.trial_judging_types import TrialJudgeVerdicts, TrialRunEvidence, TrialRunJudgment
from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.facade.contracts import TaskRunDTO, TaskRunInputFile

JUDGE_MAX_RUNTIME_SECONDS = 30 * 60
JUDGE_SANDBOX_ENVIRONMENT = "SIGNALS_SCOUT_TRIAL_JUDGE"


def _judging_input(snapshot: TrialEvaluationSnapshot) -> TrialJudgeInput:
    return TrialJudgeInput(
        criteria=snapshot.criteria,
        rubric_reference_context=snapshot.rubric_reference_context.model_dump(mode="json"),
        judge_model=snapshot.judge_model,
        judge_prompt_version=snapshot.judge_prompt_version,
    )


def _assert_scout_available(snapshot: TrialEvaluationSnapshot, evidence: TrialRunEvidence) -> None:
    assert_trial_environment_ready()
    if evidence.run_id is None or evidence.task_id is None or evidence.task_run_id is None:
        raise TrialJudgeValidationError("The saved evidence is not bound to a scout task run.")
    if evidence not in snapshot.runs:
        raise TrialJudgeValidationError("The evidence does not belong to this evaluation.")
    if evidence.execution_status != "completed" or evidence.exclusion_reason is not None:
        raise TrialJudgeValidationError("The saved scout run is not eligible for judging.")
    run = (
        SignalScoutRun.objects.for_team(snapshot.team_id)
        .select_related("task_run__task")
        .filter(
            id=evidence.run_id,
            scout_config_id=snapshot.config_id,
            skill_name=snapshot.rubric_reference_context.skill_name,
            task_run_id=evidence.task_run_id,
            task_run__team_id=snapshot.team_id,
            task_run__task_id=evidence.task_id,
            task_run__task__team_id=snapshot.team_id,
            task_run__task__created_by_id=snapshot.user_id,
            task_run__task__deleted=False,
            task_run__task__origin_product="signals_scout",
            task_run__task__origin_key=f"scout-trial:{evidence.launch_id}",
        )
        .first()
    )
    marker = (run.metadata or {}).get("scout_trial") if run is not None else None
    if (
        run is None
        or not isinstance(marker, dict)
        or marker.get("version") != 1
        or marker.get("launch_id") != str(evidence.launch_id)
        or marker.get("context_id") != str(snapshot.context_id)
        or run.task_run.status != "completed"
    ):
        raise TrialJudgeValidationError("The saved scout run is no longer available for this evaluation.")
    if ScoutTrialStore(run).invalid_reason() is not None:
        raise TrialJudgeValidationError("The scout trial was invalidated after its evidence was saved.")


def _token_count(state: dict[str, object], field_name: str) -> int | None:
    usage = state.get("token_usage")
    value = usage.get(field_name) if isinstance(usage, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


@frozen
class _JudgeRun:
    snapshot: TrialEvaluationSnapshot = field(repr=False)
    evidence: TrialRunEvidence = field(repr=False)
    prompt: str = field(repr=False)

    def bind_before_dispatch(self, run_id: UUID) -> dict[str, JsonValue]:
        files = [
            TaskRunInputFile(
                id=str(uuid5(run_id, file.id)),
                name=file.filename,
                storage_path=trial_evidence_storage_key(self.snapshot, self.evidence, file),
                size_bytes=file.size_bytes,
                content_type="application/x-ndjson" if file.kind == "trace" else "text/plain",
            )
            for file in self.evidence.files
        ]
        tasks_facade.attach_task_run_input_files(team_id=self.snapshot.team_id, run_id=run_id, files=files)
        return {
            "pending_user_message": self.prompt,
            # Startup and Temporal forwarding must recognize the same initial message.
            "pending_user_message_id": str(run_id),
            "pending_user_artifact_ids": [file.id for file in files],
            "mcp_gateway_server_ids": [],
            "include_live_context": False,
        }

    @property
    def origin_key(self) -> str:
        return f"scout-trial-judge:{self.snapshot.evaluation_id}:{self.evidence.launch_id}"

    def existing(self) -> TaskRunDTO | None:
        task = tasks_facade.get_task_by_origin_key(self.snapshot.team_id, self.origin_key)
        if task is None:
            return None
        if task.latest_run_id is None:
            raise TrialJudgeExecutionError("The saved judge task has no run.")
        run = tasks_facade.get_task_run(task.latest_run_id, team_id=self.snapshot.team_id)
        if (
            run is None
            or run.task_id != task.id
            or run.created_by_id != self.snapshot.user_id
            or run.task_origin_product != tasks_facade.TaskOriginProduct.SIGNALS_SCOUT_SUGGESTIONS
        ):
            raise TrialJudgeExecutionError("The saved judge task is unavailable for this evaluation.")
        return run

    def create(self) -> TaskRunDTO:
        team = Team.objects.get(pk=self.snapshot.team_id)
        assert_trial_work_enabled(team)
        environment_id = get_or_create_signals_sandbox_env(
            self.snapshot.team_id,
            JUDGE_SANDBOX_ENVIRONMENT,
            tasks_facade.SandboxNetworkAccessLevel.CUSTOM,
            allowed_domains=[],
            include_default_domains=False,
        )
        try:
            created = tasks_facade.create_and_run_task(
                team=team,
                title="[sandbox_prompt:scout_trial_judge] Assess a saved scout run",
                description=self.prompt,
                # Reuse rubric generation's repo-less internal sandbox policy.
                origin_product=tasks_facade.TaskOriginProduct.SIGNALS_SCOUT_SUGGESTIONS,
                origin_key=self.origin_key,
                user_id=self.snapshot.user_id,
                create_pr=False,
                mode="background",
                internal=True,
                sandbox_environment_id=environment_id,
                posthog_mcp_scopes=[],
                model=self.snapshot.judge_model,
                runtime_adapter="codex",
                reasoning_effort="high",
                initial_permission_mode="full-access",
                github_read_access=False,
                sandbox_timeout_seconds=JUDGE_MAX_RUNTIME_SECONDS + 120,
                inactivity_timeout_seconds=JUDGE_MAX_RUNTIME_SECONDS,
                ai_stage="scout:trial_judge",
                mcp_builtin_agent_key="scout",
                mcp_gateway_server_ids=[],
                before_task_dispatch=self.bind_before_dispatch,
                output_schema=TrialJudgeVerdicts.model_json_schema(),
            )
        except IntegrityError:
            # Task creation rolls back before this lookup; its unique origin key owns dispatch.
            existing = self.existing()
            if existing is None:
                raise
            return existing
        if created.latest_run is None:
            raise TrialJudgeExecutionError("The judge task was created without a run.")
        return created.latest_run

    def expire(self, run: TaskRunDTO) -> TaskRunDTO:
        error = "The judge did not finish within 30 minutes."
        updated = tasks_facade.update_task_run(
            run.id,
            run.task_id,
            self.snapshot.team_id,
            validated_data={"status": "failed", "error_message": error},
            only_if_non_terminal=True,
        )
        if updated is not None and updated.status == "completed":
            completed = tasks_facade.get_task_run(run.id, team_id=self.snapshot.team_id)
            if completed is not None:
                return completed
        raise TrialJudgeExecutionError(error)


async def judge_trial_run(snapshot: TrialEvaluationSnapshot, evidence: TrialRunEvidence) -> TrialRunJudgment | None:
    with private_capture_context():
        try:
            await database_sync_to_async(_assert_scout_available)(snapshot, evidence)
            prompt = trial_judging.build_trial_judge_prompt(_judging_input(snapshot), evidence)
            judge_run = _JudgeRun(snapshot=snapshot, evidence=evidence, prompt=prompt)
            run = await database_sync_to_async(judge_run.existing)()
            if run is None:
                await asyncio.to_thread(read_trial_evidence_sources, snapshot, evidence)
                run = await database_sync_to_async(judge_run.create)()
            if run.status in {"failed", "cancelled"}:
                raise TrialJudgeExecutionError(
                    "The judge task failed before saving its assessment."
                    if run.status == "failed"
                    else "The judge task was cancelled before saving its assessment."
                )
            if run.status != "completed":
                if run.created_at is None:
                    raise TrialJudgeExecutionError("The judge task has no saved start time.")
                if timezone.now() >= run.created_at + timedelta(seconds=JUDGE_MAX_RUNTIME_SECONDS):
                    run = await database_sync_to_async(judge_run.expire)(run)
                else:
                    return None
            output = run.output
            if not isinstance(output, dict) or "summary" not in output or "criteria" not in output:
                raise TrialJudgeExecutionError("The judge finished without saving its structured assessment.")
            sources = await asyncio.to_thread(read_trial_evidence_sources, snapshot, evidence)
            verdicts = parse_trial_judgment(
                json.dumps({"summary": output["summary"], "criteria": output["criteria"]}, ensure_ascii=False),
                criteria=snapshot.criteria,
                sources=sources,
            )
            return TrialRunJudgment(
                launch_id=evidence.launch_id,
                variant_id=evidence.variant_id,
                status="judged",
                summary=verdicts.summary,
                criteria=verdicts.criteria,
                input_tokens=_token_count(run.state, "input_tokens"),
                output_tokens=_token_count(run.state, "output_tokens"),
            )
        except (TrialJudgeValidationError, TrialEvaluationError) as error:
            raise TrialJudgeExecutionError(str(error)) from None
