import asyncio
import datetime as dt
from typing import cast
from uuid import UUID

import temporalio.workflow as wf
from temporalio import common
from temporalio.common import SearchAttributePair, TypedSearchAttributes, WorkflowIDReusePolicy

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.errors import MAX_ERROR_MESSAGE_CHARS, truncate_for_temporal_payload, unwrap_temporal_cause
from posthog.temporal.common.search_attributes import POSTHOG_SESSION_RECORDING_ID_KEY, POSTHOG_TEAM_ID_KEY
from posthog.temporal.session_replay.rasterize_recording.types import RasterizeRecordingInputs

with wf.unsafe.imports_passed_through():
    from django.conf import settings

from products.replay_vision.backend.models.replay_scanner import ScannerType
from products.replay_vision.backend.temporal.activities import (
    call_scanner_provider_activity,
    cleanup_gemini_file_activity,
    create_observation_activity,
    embed_observation_activity,
    emit_classifier_tags_activity,
    emit_observation_event_activity,
    emit_observation_signal_activity,
    ensure_session_asset_activity,
    fetch_session_events_activity,
    mark_observation_failed_activity,
    mark_observation_ineligible_activity,
    mark_observation_running_activity,
    mark_observation_succeeded_activity,
    upload_video_to_gemini_activity,
)
from products.replay_vision.backend.temporal.constants import APPLY_SCANNER_WORKFLOW_NAME
from products.replay_vision.backend.temporal.errors import (
    INELIGIBLE_SESSION_ERROR_TYPE,
    SCANNER_FAILURE_ERROR_TYPE,
    FailureKind,
    ScannerFailureError,
)
from products.replay_vision.backend.temporal.scanners.classifier import ClassifierOutput
from products.replay_vision.backend.temporal.scanners.summarizer import SummarizerOutput
from products.replay_vision.backend.temporal.types import (
    OBSERVATION_PHASE_INDEX,
    OBSERVATION_PHASE_ORDER,
    ApplyScannerInputs,
    CallScannerProviderInputs,
    CleanupGeminiFileInputs,
    CreateObservationInputs,
    CreateObservationOutput,
    EmbedObservationInputs,
    EmitClassifierTagsInputs,
    EmitObservationEventInputs,
    EmitObservationSignalInputs,
    EnsureSessionAssetInputs,
    EnsureSessionAssetOutput,
    FetchSessionEventsInputs,
    MarkObservationFailedInputs,
    MarkObservationIneligibleInputs,
    MarkObservationRunningInputs,
    MarkObservationSucceededInputs,
    ObservationProgress,
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

# Generous because fetch's deterministic errors are non_retryable; this budget only covers transient infra (e.g. ClickHouse at capacity).
_FETCH_RETRY = common.RetryPolicy(
    initial_interval=dt.timedelta(seconds=2),
    maximum_interval=dt.timedelta(seconds=60),
    maximum_attempts=6,
)

# A transient shared-DB slowdown can time this out; retry like the other state activities (the get-or-create makes sequential retries dedup-safe).
_ENSURE_ASSET_RETRY = common.RetryPolicy(
    initial_interval=dt.timedelta(seconds=1),
    maximum_interval=dt.timedelta(seconds=10),
    maximum_attempts=5,
)

# Deterministic failures opt out via ScannerFailureError's non_retryable flag; only transient kinds re-run.
_UPLOAD_RETRY = common.RetryPolicy(
    initial_interval=dt.timedelta(seconds=2),
    maximum_interval=dt.timedelta(seconds=30),
    maximum_attempts=3,
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


def _has_embeddable_text(model_output: object) -> bool:
    """Whether an observation carries text worth embedding — summarizer facets, or a `reasoning` paragraph."""
    if isinstance(model_output, SummarizerOutput):
        return model_output.has_any_facet()
    reasoning = getattr(model_output, "reasoning", "")
    return bool(reasoning and reasoning.strip())


def _extract_kind_for_type(e: BaseException, expected_type: str) -> str | None:
    """Pull a kind string off a kinded ApplicationError, surviving Temporal's ActivityError wrap."""
    cause = unwrap_temporal_cause(e) or e
    if getattr(cause, "type", None) != expected_type:
        return None
    details = getattr(cause, "details", None)
    return details[0] if details else None


def _root_cause_message(e: BaseException) -> str:
    """Bare message from the root cause — no `TypeName:` prefix; the kind label takes that role."""
    cause = unwrap_temporal_cause(e) or e
    msg = getattr(cause, "message", None) or str(cause) or type(cause).__name__
    return truncate_for_temporal_payload(msg, MAX_ERROR_MESSAGE_CHARS)


def _encode_reason(kind: str, message: str) -> str:
    """`kind:message` — the frontend splits on the first colon to render the kind as a badge."""
    return f"{kind}:{message}"


def _rasterizer_workflow_id(inputs: ApplyScannerInputs) -> str:
    # Per-scanner child id so concurrent observations of the same session don't collide on WorkflowAlreadyStartedError.
    return f"replay-vision-rasterize-{inputs.team_id}-{inputs.session_id}-{inputs.scanner_id}"


@wf.defn(name=APPLY_SCANNER_WORKFLOW_NAME)
class ApplyScannerWorkflow(PostHogWorkflow):
    """Apply one scanner to one session: create row → fetch+rasterize → upload → call provider → emit event → mark succeeded."""

    inputs_cls = ApplyScannerInputs

    def __init__(self) -> None:
        self._progress: ObservationProgress = {
            "phase": OBSERVATION_PHASE_ORDER[0],
            "step": 0,
            "total_steps": len(OBSERVATION_PHASE_ORDER),
            "rasterizer_workflow_id": None,
        }

    @wf.query
    def get_progress(self) -> ObservationProgress:
        # Copy so Temporal serializes a stable snapshot without racing the run() coroutine.
        return cast(ObservationProgress, dict(self._progress))

    def _advance_phase(self, phase: str, rasterizer_workflow_id: str | None = None) -> None:
        self._progress["phase"] = phase
        self._progress["step"] = OBSERVATION_PHASE_INDEX[phase]
        if rasterizer_workflow_id is not None:
            self._progress["rasterizer_workflow_id"] = rasterizer_workflow_id

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
        if not create_result.was_created or create_result.observation_id is None:
            return  # Either an existing observation owns this (scanner, session_id), or the org's monthly quota is exhausted.

        observation_id = create_result.observation_id
        scanner_type = create_result.scanner_type
        await wf.execute_activity(
            mark_observation_running_activity,
            MarkObservationRunningInputs(observation_id=observation_id),
            start_to_close_timeout=dt.timedelta(seconds=30),
            retry_policy=_STATE_ACTIVITY_RETRY,
        )
        self._advance_phase("fetching")

        uploaded: UploadedVideo | None = None
        try:
            asset_result = await self._fetch_and_ensure_asset(inputs, observation_id)
            self._advance_phase("rendering", rasterizer_workflow_id=_rasterizer_workflow_id(inputs))
            await self._run_rasterize_child(inputs, asset_result.asset_id)
            self._advance_phase("uploading")
            uploaded = await wf.execute_activity(
                upload_video_to_gemini_activity,
                UploadVideoToGeminiInputs(asset_id=asset_result.asset_id),
                start_to_close_timeout=dt.timedelta(minutes=10),
                retry_policy=_UPLOAD_RETRY,
            )
            self._advance_phase("analyzing")
            call_output: ScannerCallOutput = await wf.execute_activity(
                call_scanner_provider_activity,
                CallScannerProviderInputs(
                    team_id=inputs.team_id,
                    observation_id=observation_id,
                    file_uri=uploaded.file_uri,
                    mime_type=uploaded.mime_type,
                ),
                # Multi-turn tool conversation (video + on-demand event lookups) needs more headroom than a single call.
                start_to_close_timeout=dt.timedelta(minutes=10),
                retry_policy=_PROVIDER_CALL_RETRY,
            )
            self._advance_phase("finalizing")
            await self._apply_scanner_side_effects(inputs, observation_id, call_output.model_output)
            signals_count = 0
            if call_output.signals:
                # The activity fails soft (returns 0 on any error), so there's nothing to retry. The local
                # catch covers Temporal-level failures (timeout, worker loss) — emission is advisory and
                # must never demote an otherwise-successful observation to FAILED.
                try:
                    signals_count = await wf.execute_activity(
                        emit_observation_signal_activity,
                        EmitObservationSignalInputs(
                            team_id=inputs.team_id,
                            observation_id=observation_id,
                            exported_asset_id=asset_result.asset_id,
                            signals=call_output.signals,
                        ),
                        start_to_close_timeout=dt.timedelta(seconds=30),
                        retry_policy=common.RetryPolicy(maximum_attempts=1),
                    )
                except Exception:
                    wf.logger.exception("Signal emission activity failed for observation %s", observation_id)
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
                    scanner_type=scanner_type,
                    scanner_result=ScannerResult(model_output=call_output.model_output, signals_count=signals_count),
                ),
                start_to_close_timeout=dt.timedelta(seconds=30),
                retry_policy=_STATE_ACTIVITY_RETRY,
            )
        except Exception as e:
            ineligible_kind = _extract_kind_for_type(e, INELIGIBLE_SESSION_ERROR_TYPE)
            if ineligible_kind is not None:
                await self._mark_ineligible(observation_id, scanner_type, ineligible_kind, _root_cause_message(e))
            else:
                failure_kind = _extract_kind_for_type(e, SCANNER_FAILURE_ERROR_TYPE) or FailureKind.INTERNAL_ERROR.value
                await self._mark_failed(observation_id, scanner_type, failure_kind, _root_cause_message(e))
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
        try:
            await wf.execute_child_workflow(
                "rasterize-recording",
                RasterizeRecordingInputs(exported_asset_id=asset_id, product="replay_vision"),
                id=_rasterizer_workflow_id(inputs),
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
        except Exception as e:
            # Re-classify the rasterizer's failure so the user sees a rasterizer label, not a generic "internal error".
            raise ScannerFailureError(_root_cause_message(e), kind=FailureKind.RASTERIZATION_FAILED) from e

    async def _mark_failed(self, observation_id: UUID, scanner_type: ScannerType, kind: str, message: str) -> None:
        await wf.execute_activity(
            mark_observation_failed_activity,
            MarkObservationFailedInputs(
                observation_id=observation_id,
                scanner_type=scanner_type,
                error_reason=_encode_reason(kind, message),
            ),
            start_to_close_timeout=dt.timedelta(seconds=30),
            retry_policy=_STATE_ACTIVITY_RETRY,
        )

    async def _mark_ineligible(self, observation_id: UUID, scanner_type: ScannerType, kind: str, message: str) -> None:
        await wf.execute_activity(
            mark_observation_ineligible_activity,
            MarkObservationIneligibleInputs(
                observation_id=observation_id,
                scanner_type=scanner_type,
                error_reason=_encode_reason(kind, message),
            ),
            start_to_close_timeout=dt.timedelta(seconds=30),
            retry_policy=_STATE_ACTIVITY_RETRY,
        )

    async def _apply_scanner_side_effects(
        self,
        inputs: ApplyScannerInputs,
        observation_id: UUID,
        model_output: object,
    ) -> None:
        """Dispatch scanner-type-specific side-effects after the LLM call; failure aborts the workflow.

        DEPLOY NOTE (accepted in-flight breakage): this dispatch was changed — the summarizer embed activity was
        renamed and an embed step was added for every scanner type. We deliberately do NOT gate it behind
        `workflow.patched()` (a pattern this codebase doesn't otherwise use). ApplyScannerWorkflow runs are short
        (≤1h timeout), so the only affected runs are the handful in flight *past this step* at the deploy instant:
        they may hit a replay non-determinism error and stall until their timeout, costing at most a few
        re-runnable observations. The `embed_summarizer_observation_activity` alias additionally lets any
        already-scheduled old-name task resolve. This trade-off is accepted over carrying a permanent patch gate.
        """
        # Embed the observation's explanation text (reasoning, or summarizer facets) for natural-language search.
        if _has_embeddable_text(model_output):
            await wf.execute_activity(
                embed_observation_activity,
                EmbedObservationInputs(
                    team_id=inputs.team_id,
                    session_id=inputs.session_id,
                    observation_id=observation_id,
                    scanner_id=inputs.scanner_id,
                    model_output=model_output,
                ),
                start_to_close_timeout=dt.timedelta(seconds=30),
                retry_policy=_SIDE_EFFECT_RETRY,
            )
        # Classifiers additionally fan their tags out onto the recording.
        if isinstance(model_output, ClassifierOutput):
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
