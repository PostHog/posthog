"""Re-run the scanner (suggested prompt, current config) against rated sessions, recording per-session
outcomes on the suggestion's `evaluation` JSON. Reuses the observation pipeline's activities but never
creates observation rows."""

import asyncio
import datetime as dt

import temporalio.workflow as wf
from temporalio import common
from temporalio.common import SearchAttributePair, TypedSearchAttributes, WorkflowIDReusePolicy

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.errors import unwrap_temporal_cause
from posthog.temporal.common.search_attributes import POSTHOG_SESSION_RECORDING_ID_KEY, POSTHOG_TEAM_ID_KEY
from posthog.temporal.session_replay.rasterize_recording.types import RasterizeRecordingInputs

with wf.unsafe.imports_passed_through():
    from django.conf import settings

from products.replay_vision.backend.temporal.activities import (
    cleanup_gemini_file_activity,
    ensure_session_asset_activity,
    fetch_session_events_activity,
    upload_video_to_gemini_activity,
)
from products.replay_vision.backend.temporal.activities.call_scanner_provider import call_scanner_provider_activity
from products.replay_vision.backend.temporal.activities.evaluate_prompt_suggestion import (
    finalize_evaluation_activity,
    record_evaluation_result_activity,
    select_evaluation_sessions_activity,
)
from products.replay_vision.backend.temporal.constants import EVALUATE_PROMPT_SUGGESTION_WORKFLOW_NAME
from products.replay_vision.backend.temporal.evaluation_types import (
    EvaluatePromptSuggestionInputs,
    EvaluationSession,
    FinalizeEvaluationInputs,
    RecordEvaluationResultInputs,
    SelectEvaluationSessionsInputs,
    SelectEvaluationSessionsOutput,
)
from products.replay_vision.backend.temporal.types import (
    CallScannerProviderInputs,
    CleanupGeminiFileInputs,
    EnsureSessionAssetInputs,
    FetchSessionEventsInputs,
    ScannerCallOutput,
    UploadedVideo,
    UploadVideoToGeminiInputs,
)

# Each session is a full video upload + LLM conversation, so two at a time bounds worker load.
_EVALUATION_CONCURRENCY = 2

_STATE_RETRY = common.RetryPolicy(
    initial_interval=dt.timedelta(seconds=1),
    maximum_interval=dt.timedelta(seconds=10),
    maximum_attempts=5,
)
_STEP_RETRY = common.RetryPolicy(
    initial_interval=dt.timedelta(seconds=2),
    maximum_interval=dt.timedelta(seconds=30),
    maximum_attempts=3,
)


def _cause_message(e: BaseException) -> str:
    cause = unwrap_temporal_cause(e) or e
    return str(getattr(cause, "message", None) or cause or type(cause).__name__)[:500]


@wf.defn(name=EVALUATE_PROMPT_SUGGESTION_WORKFLOW_NAME)
class EvaluatePromptSuggestionWorkflow(PostHogWorkflow):
    """Evaluate one prompt suggestion against its scanner's rated sessions."""

    inputs_cls = EvaluatePromptSuggestionInputs

    @wf.run
    async def run(self, inputs: EvaluatePromptSuggestionInputs) -> None:
        selection: SelectEvaluationSessionsOutput = await wf.execute_activity(
            select_evaluation_sessions_activity,
            SelectEvaluationSessionsInputs(
                suggestion_id=inputs.suggestion_id, team_id=inputs.team_id, session_limit=inputs.session_limit
            ),
            start_to_close_timeout=dt.timedelta(minutes=1),
            retry_policy=_STATE_RETRY,
        )
        try:
            semaphore = asyncio.Semaphore(_EVALUATION_CONCURRENCY)

            async def evaluate_one(session: EvaluationSession) -> None:
                async with semaphore:
                    await self._evaluate_session(inputs, selection, session)

            await asyncio.gather(*(evaluate_one(session) for session in selection.sessions))
        except Exception:
            await self._finalize(inputs, failed=True)
            raise
        await self._finalize(inputs, failed=False)

    async def _evaluate_session(
        self,
        inputs: EvaluatePromptSuggestionInputs,
        selection: SelectEvaluationSessionsOutput,
        session: EvaluationSession,
    ) -> None:
        """Run one session with the suggested prompt. Failures record an error result instead of failing the run."""
        uploaded: UploadedVideo | None = None
        try:
            fetch_task = wf.execute_activity(
                fetch_session_events_activity,
                FetchSessionEventsInputs(
                    observation_id=session.observation_id,
                    team_id=inputs.team_id,
                    session_id=session.session_id,
                ),
                start_to_close_timeout=dt.timedelta(minutes=2),
                retry_policy=_STEP_RETRY,
            )
            asset_task = wf.execute_activity(
                ensure_session_asset_activity,
                EnsureSessionAssetInputs(team_id=inputs.team_id, session_id=session.session_id),
                start_to_close_timeout=dt.timedelta(seconds=30),
                retry_policy=_STATE_RETRY,
            )
            _, asset_result = await asyncio.gather(fetch_task, asset_task)
            await wf.execute_child_workflow(
                "rasterize-recording",
                RasterizeRecordingInputs(exported_asset_id=asset_result.asset_id, product="replay_vision"),
                id=f"replay-vision-eval-rasterize-{inputs.team_id}-{session.session_id}-{inputs.suggestion_id}",
                task_queue=settings.SESSION_REPLAY_TASK_QUEUE,
                retry_policy=common.RetryPolicy(maximum_attempts=int(settings.TEMPORAL_WORKFLOW_MAX_ATTEMPTS)),
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                execution_timeout=dt.timedelta(minutes=30),
                search_attributes=TypedSearchAttributes(
                    search_attributes=[
                        SearchAttributePair(key=POSTHOG_TEAM_ID_KEY, value=inputs.team_id),
                        SearchAttributePair(key=POSTHOG_SESSION_RECORDING_ID_KEY, value=session.session_id),
                    ]
                ),
            )
            uploaded = await wf.execute_activity(
                upload_video_to_gemini_activity,
                UploadVideoToGeminiInputs(asset_id=asset_result.asset_id),
                start_to_close_timeout=dt.timedelta(minutes=10),
                retry_policy=_STEP_RETRY,
            )
            call_output: ScannerCallOutput = await wf.execute_activity(
                call_scanner_provider_activity,
                CallScannerProviderInputs(
                    team_id=inputs.team_id,
                    observation_id=session.observation_id,
                    file_uri=uploaded.file_uri,
                    mime_type=uploaded.mime_type,
                    snapshot_override=selection.snapshot,
                ),
                start_to_close_timeout=dt.timedelta(minutes=10),
                retry_policy=_STEP_RETRY,
            )
            await self._record(inputs, session, after_output=call_output.model_output.model_dump(mode="json"))
        except Exception as e:
            await self._record(inputs, session, error=_cause_message(e))
        finally:
            if uploaded is not None:
                try:
                    await wf.execute_activity(
                        cleanup_gemini_file_activity,
                        CleanupGeminiFileInputs(gemini_file_name=uploaded.gemini_file_name),
                        start_to_close_timeout=dt.timedelta(seconds=30),
                        retry_policy=common.RetryPolicy(maximum_attempts=2),
                    )
                except Exception:
                    pass

    async def _record(
        self,
        inputs: EvaluatePromptSuggestionInputs,
        session: EvaluationSession,
        after_output: dict | None = None,
        error: str | None = None,
    ) -> None:
        await wf.execute_activity(
            record_evaluation_result_activity,
            RecordEvaluationResultInputs(
                suggestion_id=inputs.suggestion_id,
                team_id=inputs.team_id,
                session=session,
                after_output=after_output,
                error=error,
            ),
            start_to_close_timeout=dt.timedelta(seconds=30),
            retry_policy=_STATE_RETRY,
        )

    async def _finalize(self, inputs: EvaluatePromptSuggestionInputs, failed: bool) -> None:
        try:
            await wf.execute_activity(
                finalize_evaluation_activity,
                FinalizeEvaluationInputs(suggestion_id=inputs.suggestion_id, team_id=inputs.team_id, failed=failed),
                start_to_close_timeout=dt.timedelta(seconds=30),
                retry_policy=_STATE_RETRY,
            )
        except Exception:
            wf.logger.exception("Failed to finalize evaluation for suggestion %s", inputs.suggestion_id)
