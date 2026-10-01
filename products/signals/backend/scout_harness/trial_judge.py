from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import field
from typing import TYPE_CHECKING

from posthog.dataclasses import frozen
from posthog.llm.gateway_client import build_async_openai_client, private_scout_gateway
from posthog.sync import database_sync_to_async

from products.signals.backend import trial_judging
from products.signals.backend.models import SignalScoutRun
from products.signals.backend.scout_harness.trial_evaluation_types import TrialEvaluationSnapshot
from products.signals.backend.scout_harness.trial_gateway import create_trial_gateway_token, revoke_trial_gateway_token
from products.signals.backend.scout_harness.trial_launch import assert_trial_environment_ready
from products.signals.backend.scout_harness.trial_state import ScoutTrialStore
from products.signals.backend.trial_judging import (
    JUDGE_PROMPT_VERSION as JUDGE_PROMPT_VERSION,
    MAX_JUDGE_INPUT_CHARACTERS as MAX_JUDGE_INPUT_CHARACTERS,
    MAX_JUDGE_OUTPUT_CHARACTERS as MAX_JUDGE_OUTPUT_CHARACTERS,
    MAX_TRACE_CHARACTERS as MAX_TRACE_CHARACTERS,
    MAX_TRACE_INPUT_CHARACTERS as MAX_TRACE_INPUT_CHARACTERS,
    MAX_TRACE_SOURCE_CHARACTERS as MAX_TRACE_SOURCE_CHARACTERS,
    MAX_TRACE_SOURCES as MAX_TRACE_SOURCES,
    TrialJudgeExecutionError as TrialJudgeExecutionError,
    TrialJudgeInput,
    TrialJudgeValidationError as TrialJudgeValidationError,
    TrialTraceEvidence as TrialTraceEvidence,
    evidence_sources_from_logs as evidence_sources_from_logs,
    parse_trial_judgment as parse_trial_judgment,
    safe_judge_failure as safe_judge_failure,
)
from products.signals.backend.trial_judging_types import TrialRunEvidence, TrialRunJudgment

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from openai import AsyncOpenAI
    from openai.types.chat import ChatCompletionMessageParam


def _judging_input(snapshot: TrialEvaluationSnapshot) -> TrialJudgeInput:
    return TrialJudgeInput(
        criteria=snapshot.criteria,
        rubric_reference_context=(
            snapshot.rubric_reference_context.model_dump(mode="json")
            if snapshot.rubric_reference_context is not None
            else None
        ),
        judge_model=snapshot.judge_model,
        judge_prompt_version=snapshot.judge_prompt_version,
    )


def bound_trial_judge_evidence(snapshot: TrialEvaluationSnapshot, evidence: TrialRunEvidence) -> TrialRunEvidence:
    return trial_judging.bound_trial_judge_evidence(_judging_input(snapshot), evidence)


def build_trial_judge_messages(
    snapshot: TrialEvaluationSnapshot, evidence: TrialRunEvidence
) -> list[ChatCompletionMessageParam]:
    return trial_judging.build_trial_judge_messages(_judging_input(snapshot), evidence)


def _create_judge_token(snapshot: TrialEvaluationSnapshot, evidence: TrialRunEvidence) -> str:
    assert_trial_environment_ready()
    if evidence.run_id is None or evidence.task_id is None or evidence.task_run_id is None:
        raise TrialJudgeValidationError("The saved evidence is not bound to a scout task run.")
    if evidence not in snapshot.runs:
        raise TrialJudgeValidationError("The evidence does not belong to this evaluation.")
    run = (
        SignalScoutRun.objects.for_team(snapshot.team_id)
        .select_related("task_run__task")
        .filter(
            id=evidence.run_id,
            scout_config_id=snapshot.config_id,
            task_run_id=evidence.task_run_id,
            task_run__team_id=snapshot.team_id,
            task_run__task_id=evidence.task_id,
            task_run__task__team_id=snapshot.team_id,
            task_run__task__created_by_id=snapshot.user_id,
            task_run__task__deleted=False,
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
    # Minting also verifies task origin, the task-state marker, and the operator's current project access.
    return create_trial_gateway_token(run)


@frozen
class _ScoutTrialJudgeGateway:
    snapshot: TrialEvaluationSnapshot = field(repr=False)
    evidence: TrialRunEvidence = field(repr=False)

    async def mint(self) -> str:
        return await database_sync_to_async(_create_judge_token, thread_sensitive=False)(self.snapshot, self.evidence)

    @asynccontextmanager
    async def open_client(self, token: str, *, timeout: float) -> AsyncIterator[AsyncOpenAI]:
        with private_scout_gateway(token):
            async with build_async_openai_client(
                product="signals", ai_product="signals_scout", properties={"team_id": str(self.snapshot.team_id)}
            ).with_options(max_retries=0, timeout=timeout) as client:
                yield client

    async def revoke(self, token: str) -> None:
        await database_sync_to_async(revoke_trial_gateway_token, thread_sensitive=False)(token)


async def judge_trial_run(snapshot: TrialEvaluationSnapshot, evidence: TrialRunEvidence) -> TrialRunJudgment:
    return await trial_judging.judge_trial_run(
        _judging_input(snapshot), evidence, _ScoutTrialJudgeGateway(snapshot=snapshot, evidence=evidence)
    )
