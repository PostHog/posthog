import asyncio
import datetime as dt
from uuid import UUID

import temporalio.workflow as wf
from temporalio import common
from temporalio.common import SearchAttributePair, TypedSearchAttributes, WorkflowIDReusePolicy

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.search_attributes import POSTHOG_SESSION_RECORDING_ID_KEY, POSTHOG_TEAM_ID_KEY
from posthog.temporal.session_replay.rasterize_recording.types import RasterizeRecordingInputs

with wf.unsafe.imports_passed_through():
    from django.conf import settings

from products.replay_vision.backend.temporal.activities import (
    call_scanner_provider_activity,
    cleanup_gemini_file_activity,
    create_observation_activity,
    embed_indexer_observation_activity,
    emit_classifier_tags_activity,
    emit_observation_event_activity,
    ensure_session_asset_activity,
    fetch_session_events_activity,
    mark_observation_failed_activity,
    mark_observation_running_activity,
    mark_observation_succeeded_activity,
    upload_video_to_gemini_activity,
)
from products.replay_vision.backend.temporal.constants import APPLY_SCANNER_WORKFLOW_NAME
from products.replay_vision.backend.temporal.scanners.classifier import ClassifierOutput
from products.replay_vision.backend.temporal.scanners.indexer import IndexerOutput
from products.replay_vision.backend.temporal.types import (
    ApplyScannerInputs,
    CallScannerProviderInputs,
    CleanupGeminiFileInputs,
    CreateObservationInputs,
    CreateObservationOutput,
    EmbedIndexerObservationInputs,
    EmitClassifierTagsInputs,
    EmitObservationEventInputs,
    EnsureSessionAssetInputs,
    EnsureSessionAssetOutput,
    FetchSessionEventsInputs,
    MarkObservationFailedInputs,
    MarkObservationRunningInputs,
    MarkObservationSucceededInputs,
    ScannerCallOutput,
    ScannerResult,
    UploadedVideo,
    UploadVideoToGeminiInputs,
)

_STATE_ACTIVITY_RETRY = common.RetryPolicy(
    initial_interval=dt.timedelta(seconds=1),
    maximum_interval=dt.timedelta(seconds=10),
    maximum_attempts=5,
)

# Create's `ValueError` paths (scanner missing, user not in org) won't recover on retry.
_CREATE_OBSERVATION_RETRY = common.RetryPolicy(
    initial_interval=dt.timedelta(seconds=1),
    maximum_interval=dt.timedelta(seconds=10),
    maximum_attempts=5,
    non_retryable_error_types=["ValueError"],
)

_FETCH_RETRY = common.RetryPolicy(
    initial_interval=dt.timedelta(seconds=2),
    maximum_interval=dt.timedelta(seconds=30),
    maximum_attempts=3,
)

# Asset get-or-create has no transient failure modes worth retrying.
_ENSURE_ASSET_RETRY = common.RetryPolicy(maximum_attempts=1)

# Deterministic failures don't retry; a re-upload would leak another Gemini file before the cleanup sweep reaps it.
_UPLOAD_RETRY = common.RetryPolicy(
    initial_interval=dt.timedelta(seconds=2),
    maximum_interval=dt.timedelta(seconds=30),
    maximum_attempts=3,
    non_retryable_error_types=["RuntimeError", "ValueError"],
)

# Workflow-level retries only cover transient transport failures; schema/semantic errors are non-retryable.
_PROVIDER_CALL_RETRY = common.RetryPolicy(
    initial_interval=dt.timedelta(seconds=2),
    maximum_interval=dt.timedelta(seconds=30),
    maximum_attempts=3,
)

# Cleanup is best-effort; the cleanup sweep handles persistent failures.
_CLEANUP_RETRY = common.RetryPolicy(maximum_attempts=2)

# Side-effects (embeddings, tag emission) — bounded retries on transient transport failures.
_SIDE_EFFECT_RETRY = common.RetryPolicy(
    initial_interval=dt.timedelta(seconds=1),
    maximum_interval=dt.timedelta(seconds=10),
    maximum_attempts=3,
)


@wf.defn(name=APPLY_SCANNER_WORKFLOW_NAME)
class ApplyScannerWorkflow(PostHogWorkflow):
    """Apply one scanner to one session: create row → fetch+rasterize → upload → call provider → emit event → mark succeeded."""

    inputs_cls = ApplyScannerInputs

    @wf.run
    async def run(self, inputs: ApplyScannerInputs) -> None:
        workflow_id = wf.info().workflow_id

        create_result: CreateObservationOutput = await wf.execute_activity(
            create_observation_activity,
            CreateObservationInputs(
                scanner_id=inputs.scanner_id,
                team_id=inputs.team_id,
                session_id=inputs.session_id,
                triggered_by=inputs.triggered_by,
                triggered_by_user_id=inputs.triggered_by_user_id,
                workflow_id=workflow_id,
            ),
            start_to_close_timeout=dt.timedelta(seconds=30),
            retry_policy=_CREATE_OBSERVATION_RETRY,
        )
        if not create_result.was_created:
            return  # Existing observation owns this (scanner, session_id); its workflow drives it.

        observation_id = create_result.observation_id
        await wf.execute_activity(
            mark_observation_running_activity,
            MarkObservationRunningInputs(observation_id=observation_id),
            start_to_close_timeout=dt.timedelta(seconds=30),
            retry_policy=_STATE_ACTIVITY_RETRY,
        )

        uploaded: UploadedVideo | None = None
        try:
            asset_result = await self._fetch_and_ensure_asset(inputs, observation_id)
            await self._run_rasterize_child(inputs, asset_result.asset_id)
            uploaded = await wf.execute_activity(
                upload_video_to_gemini_activity,
                UploadVideoToGeminiInputs(asset_id=asset_result.asset_id),
                start_to_close_timeout=dt.timedelta(minutes=10),
                retry_policy=_UPLOAD_RETRY,
            )
            call_output: ScannerCallOutput = await wf.execute_activity(
                call_scanner_provider_activity,
                CallScannerProviderInputs(
                    team_id=inputs.team_id,
                    observation_id=observation_id,
                    file_uri=uploaded.file_uri,
                    mime_type=uploaded.mime_type,
                ),
                start_to_close_timeout=dt.timedelta(minutes=5),
                retry_policy=_PROVIDER_CALL_RETRY,
            )
            await self._apply_scanner_side_effects(inputs, observation_id, call_output.model_output)
            await wf.execute_activity(
                emit_observation_event_activity,
                EmitObservationEventInputs(observation_id=observation_id, model_output=call_output.model_output),
                start_to_close_timeout=dt.timedelta(seconds=30),
                retry_policy=_STATE_ACTIVITY_RETRY,
            )
            await wf.execute_activity(
                mark_observation_succeeded_activity,
                MarkObservationSucceededInputs(
                    observation_id=observation_id,
                    scanner_result=ScannerResult(
                        model_output=call_output.model_output,
                        event_id_mapping=call_output.event_id_mapping,
                    ),
                ),
                start_to_close_timeout=dt.timedelta(seconds=30),
                retry_policy=_STATE_ACTIVITY_RETRY,
            )
        except Exception as e:
            await self._mark_failed(observation_id, f"{type(e).__name__}: {e}")
            raise
        finally:
            if uploaded is not None:
                # Swallow exceptions so cleanup failure can't fail a workflow that already marked-succeeded.
                try:
                    await wf.execute_activity(
                        cleanup_gemini_file_activity,
                        CleanupGeminiFileInputs(gemini_file_name=uploaded.gemini_file_name),
                        start_to_close_timeout=dt.timedelta(seconds=30),
                        retry_policy=_CLEANUP_RETRY,
                    )
                except Exception:
                    pass

    async def _fetch_and_ensure_asset(
        self, inputs: ApplyScannerInputs, observation_id: UUID
    ) -> EnsureSessionAssetOutput:
        fetch_task = wf.execute_activity(
            fetch_session_events_activity,
            FetchSessionEventsInputs(
                observation_id=observation_id,
                team_id=inputs.team_id,
                session_id=inputs.session_id,
            ),
            start_to_close_timeout=dt.timedelta(minutes=2),
            retry_policy=_FETCH_RETRY,
        )
        asset_task = wf.execute_activity(
            ensure_session_asset_activity,
            EnsureSessionAssetInputs(team_id=inputs.team_id, session_id=inputs.session_id),
            start_to_close_timeout=dt.timedelta(seconds=30),
            retry_policy=_ENSURE_ASSET_RETRY,
        )
        _, asset_result = await asyncio.gather(fetch_task, asset_task)
        return asset_result

    async def _run_rasterize_child(self, inputs: ApplyScannerInputs, asset_id: int) -> None:
        # Per-scanner child id so concurrent observations of the same session don't collide on WorkflowAlreadyStartedError.
        await wf.execute_child_workflow(
            "rasterize-recording",
            RasterizeRecordingInputs(exported_asset_id=asset_id),
            id=f"replay-vision-rasterize-{inputs.team_id}-{inputs.session_id}-{inputs.scanner_id}",
            task_queue=settings.SESSION_REPLAY_TASK_QUEUE,
            retry_policy=common.RetryPolicy(maximum_attempts=int(settings.TEMPORAL_WORKFLOW_MAX_ATTEMPTS)),
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
            execution_timeout=dt.timedelta(minutes=30),
            search_attributes=TypedSearchAttributes(
                search_attributes=[
                    SearchAttributePair(key=POSTHOG_TEAM_ID_KEY, value=inputs.team_id),
                    SearchAttributePair(key=POSTHOG_SESSION_RECORDING_ID_KEY, value=inputs.session_id),
                ]
            ),
        )

    async def _mark_failed(self, observation_id: UUID, error_reason: str) -> None:
        await wf.execute_activity(
            mark_observation_failed_activity,
            MarkObservationFailedInputs(observation_id=observation_id, error_reason=error_reason),
            start_to_close_timeout=dt.timedelta(seconds=30),
            retry_policy=_STATE_ACTIVITY_RETRY,
        )

    async def _apply_scanner_side_effects(
        self, inputs: ApplyScannerInputs, observation_id: UUID, model_output: object
    ) -> None:
        """Dispatch scanner-type-specific side-effects after the LLM call; failure aborts the workflow."""
        if isinstance(model_output, IndexerOutput):
            await wf.execute_activity(
                embed_indexer_observation_activity,
                EmbedIndexerObservationInputs(
                    team_id=inputs.team_id,
                    session_id=inputs.session_id,
                    observation_id=observation_id,
                    indexer_output=model_output,
                ),
                start_to_close_timeout=dt.timedelta(seconds=30),
                retry_policy=_SIDE_EFFECT_RETRY,
            )
        elif isinstance(model_output, ClassifierOutput):
            await wf.execute_activity(
                emit_classifier_tags_activity,
                EmitClassifierTagsInputs(
                    team_id=inputs.team_id,
                    session_id=inputs.session_id,
                    observation_id=observation_id,
                    classifier_output=model_output,
                ),
                start_to_close_timeout=dt.timedelta(seconds=30),
                retry_policy=_SIDE_EFFECT_RETRY,
            )
