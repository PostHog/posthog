from __future__ import annotations

import asyncio
from dataclasses import field
from uuid import UUID, uuid5

from pydantic import JsonValue

from posthog.clickhouse.query_tagging import private_capture_context
from posthog.dataclasses import frozen
from posthog.sync import database_sync_to_async

from products.signals.backend import trial_judging
from products.signals.backend.models import SignalScoutRun
from products.signals.backend.scout_harness.trial_evaluation import (
    read_trial_evidence_sources,
    trial_evidence_storage_key,
)
from products.signals.backend.scout_harness.trial_evaluation_types import TrialEvaluationSnapshot
from products.signals.backend.scout_harness.trial_launch import assert_trial_environment_ready
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
from products.tasks.backend.facade.agents import CustomPromptSandboxContext, MultiTurnSession
from products.tasks.backend.facade.contracts import TaskRunInputFile

JUDGE_MAX_RUNTIME_SECONDS = 15 * 60
JUDGE_SANDBOX_ENVIRONMENT = "SIGNALS_SCOUT_TRIAL_JUDGE"
_JSON_RETRY_PROMPT = (
    "Return the complete JSON object with summary and one result per supplied criterion. "
    "Use the required schema, without prose or code fences. Preserve your assessment and exact citations. "
    "Do not invent missing evidence; mark unsupported conclusions unknown."
)


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


def _token_count(state: dict[str, object], field_name: str) -> int | None:
    usage = state.get("token_usage")
    value = usage.get(field_name) if isinstance(usage, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


@frozen(frozen=False)
class _JudgeRun:
    snapshot: TrialEvaluationSnapshot = field(repr=False)
    evidence: TrialRunEvidence = field(repr=False)
    prompt: str = field(repr=False)
    run_id: UUID | None = None

    def bind_before_dispatch(self, run_id: UUID) -> dict[str, JsonValue]:
        self.run_id = run_id
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
            "scout_trial_judge": {
                "version": 1,
                "evaluation_id": str(self.snapshot.evaluation_id),
                "launch_id": str(self.evidence.launch_id),
                "context_id": str(self.snapshot.context_id),
                "user_id": self.snapshot.user_id,
                "source_task_id": str(self.evidence.task_id),
                "source_task_run_id": str(self.evidence.task_run_id),
                "source_scout_run_id": str(self.evidence.run_id),
            },
            "pending_user_message": self.prompt,
            # Startup and Temporal forwarding must recognize the same initial message.
            "pending_user_message_id": str(run_id),
            "pending_user_artifact_ids": [file.id for file in files],
            "mcp_gateway_server_ids": [],
        }

    def fail_unfinished(self, error: str) -> None:
        if self.run_id is None:
            return
        run = tasks_facade.get_task_run(self.run_id, team_id=self.snapshot.team_id)
        if run is not None:
            tasks_facade.update_task_run(
                run.id,
                run.task_id,
                self.snapshot.team_id,
                validated_data={"status": "failed", "error_message": error},
                only_if_non_terminal=True,
            )


async def _finish_judge(session: MultiTurnSession | None, judge_run: _JudgeRun | None, failure: str | None) -> None:
    try:
        if session is not None:
            await session.end(status="failed" if failure else "completed", error=failure)
    except (Exception, asyncio.CancelledError):
        failure = failure or "The judge could not complete its sandbox cleanup."
        raise
    finally:
        if failure is not None and judge_run is not None:
            await database_sync_to_async(judge_run.fail_unfinished)(failure)


async def judge_trial_run(snapshot: TrialEvaluationSnapshot, evidence: TrialRunEvidence) -> TrialRunJudgment:
    session: MultiTurnSession | None = None
    judge_run: _JudgeRun | None = None
    failure: str | None = None
    with private_capture_context():
        try:
            await database_sync_to_async(_assert_scout_available)(snapshot, evidence)
            prompt = trial_judging.build_trial_judge_prompt(_judging_input(snapshot), evidence)
            sources = await asyncio.to_thread(read_trial_evidence_sources, snapshot, evidence)
            origin_key = f"scout-trial-judge:{snapshot.evaluation_id}:{evidence.launch_id}"
            existing = await database_sync_to_async(tasks_facade.get_task_by_origin_key)(snapshot.team_id, origin_key)
            if existing is not None:
                raise TrialJudgeExecutionError(
                    "This run already has a judge task. Start a new evaluation to judge it again."
                )
            environment_id = await database_sync_to_async(get_or_create_signals_sandbox_env)(
                snapshot.team_id,
                JUDGE_SANDBOX_ENVIRONMENT,
                tasks_facade.SandboxNetworkAccessLevel.CUSTOM,
                allowed_domains=[],
                include_default_domains=False,
            )
            context = CustomPromptSandboxContext(
                team_id=snapshot.team_id,
                user_id=snapshot.user_id,
                sandbox_environment_id=environment_id,
                posthog_mcp_scopes="signals_scout_judge",
                model=snapshot.judge_model,
                runtime_adapter="codex",
                reasoning_effort="high",
                initial_permission_mode="full-access",
                github_read_access=False,
                sandbox_timeout_seconds=JUDGE_MAX_RUNTIME_SECONDS + 120,
            )
            judge_run = _JudgeRun(snapshot=snapshot, evidence=evidence, prompt=prompt)
            async with asyncio.timeout(JUDGE_MAX_RUNTIME_SECONDS + 60):
                session, output = await MultiTurnSession.start(
                    prompt=prompt,
                    context=context,
                    model=TrialJudgeVerdicts,
                    step_name="scout_trial_judge",
                    ai_stage="scout:trial_judge",
                    origin_product=tasks_facade.TaskOriginProduct.SIGNALS_SCOUT,
                    origin_key=origin_key,
                    internal=True,
                    mcp_gateway_server_ids=[],
                    before_task_dispatch=judge_run.bind_before_dispatch,
                    max_poll_seconds=JUDGE_MAX_RUNTIME_SECONDS,
                    json_retry_prompt=_JSON_RETRY_PROMPT,
                )
                verdicts = parse_trial_judgment(output.model_dump_json(), criteria=snapshot.criteria, sources=sources)
            run = await database_sync_to_async(tasks_facade.get_task_run)(session.task_run.id, team_id=snapshot.team_id)
            return TrialRunJudgment(
                launch_id=evidence.launch_id,
                variant_id=evidence.variant_id,
                status="judged",
                summary=verdicts.summary,
                criteria=verdicts.criteria,
                input_tokens=_token_count(run.state, "input_tokens") if run is not None else None,
                output_tokens=_token_count(run.state, "output_tokens") if run is not None else None,
            )
        except asyncio.CancelledError:
            failure = "The judge was cancelled before its assessment finished."
            raise
        except TrialJudgeExecutionError as error:
            failure = str(error)
            raise
        except Exception as error:
            failure = safe_judge_failure("sandbox_judge", error)
            raise TrialJudgeExecutionError(failure) from None
        finally:
            try:
                await asyncio.shield(asyncio.wait_for(_finish_judge(session, judge_run, failure), timeout=30))
            except Exception as error:
                if failure is None:
                    raise TrialJudgeExecutionError(safe_judge_failure("sandbox_cleanup", error)) from None
