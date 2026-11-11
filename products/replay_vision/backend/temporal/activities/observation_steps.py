"""Folded apply-scanner steps: Temporal bills each scheduled activity, so the cheap steps around the model call share one."""

import time
import asyncio
from collections.abc import Awaitable, Callable

from asgiref.sync import async_to_sync, sync_to_async
from temporalio import activity

from products.replay_vision.backend.temporal.activities.cleanup_gemini_file import cleanup_gemini_file_activity
from products.replay_vision.backend.temporal.activities.embed_observation import embed_observation_activity
from products.replay_vision.backend.temporal.activities.emit_classifier_tags import emit_classifier_tags_activity
from products.replay_vision.backend.temporal.activities.emit_observation_event import emit_observation_event_activity
from products.replay_vision.backend.temporal.activities.emit_observation_signal import (
    emit_observation_signal_summaries_activity,
)
from products.replay_vision.backend.temporal.activities.ensure_session_asset import ensure_session_asset_activity
from products.replay_vision.backend.temporal.activities.fetch_session_events import fetch_session_events_activity
from products.replay_vision.backend.temporal.activities.fetch_session_network import fetch_session_network_activity
from products.replay_vision.backend.temporal.activities.observation_state import (
    mark_observation_running_activity,
    mark_observation_succeeded_activity,
)
from products.replay_vision.backend.temporal.activities.resolve_experiment_variant import (
    resolve_experiment_variant_activity,
)
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.scanners.base import BaseScannerOutput
from products.replay_vision.backend.temporal.scanners.classifier import ClassifierOutput
from products.replay_vision.backend.temporal.types import (
    CleanupGeminiFileInputs,
    EmbedObservationInputs,
    EmitClassifierTagsInputs,
    EmitObservationEventInputs,
    EmitObservationSignalInputs,
    EmittedSignal,
    EnsureSessionAssetInputs,
    FetchSessionEventsInputs,
    FetchSessionNetworkInputs,
    FinalizeObservationInputs,
    MarkObservationRunningInputs,
    MarkObservationSucceededInputs,
    PrepareObservationInputs,
    PrepareObservationOutput,
    ResolveExperimentVariantInputs,
    ResolveExperimentVariantOutput,
    ScannerResult,
)

# Attempts for each fail-soft step. These steps had their own retry policies as separate activities, and a
# retry of the whole finalize activity would also repeat the steps that already succeeded.
_FAIL_SOFT_ATTEMPTS = 3


@activity.defn
@track_activity()
async def prepare_observation_activity(inputs: PrepareObservationInputs) -> PrepareObservationOutput:
    """Mark the row running, then fetch the session's events, network and asset concurrently.

    Every step is safe to repeat, so a retry of this activity re-runs all of them.
    """
    await sync_to_async(mark_observation_running_activity)(
        MarkObservationRunningInputs(observation_id=inputs.observation_id)
    )
    fetch = fetch_session_events_activity(
        FetchSessionEventsInputs(
            observation_id=inputs.observation_id, team_id=inputs.team_id, session_id=inputs.session_id
        )
    )
    asset = ensure_session_asset_activity(
        EnsureSessionAssetInputs(team_id=inputs.team_id, session_id=inputs.session_id)
    )
    network = fetch_session_network_activity(
        FetchSessionNetworkInputs(
            observation_id=inputs.observation_id, team_id=inputs.team_id, session_id=inputs.session_id
        )
    )
    resolve: Awaitable[ResolveExperimentVariantOutput | None] = (
        resolve_experiment_variant_activity(
            ResolveExperimentVariantInputs(
                observation_id=inputs.observation_id, team_id=inputs.team_id, session_id=inputs.session_id
            )
        )
        if inputs.resolve_experiment
        else _none()
    )
    # Every step runs to its end before an error is raised, so no step keeps running after the attempt fails.
    fetch_result, asset_result, network_result, resolve_result = await asyncio.gather(
        fetch, asset, network, resolve, return_exceptions=True
    )
    if isinstance(network_result, Exception):
        # The network capture is a side input that the scan can run without.
        activity.logger.warning("replay_vision.network_fetch_failed", exc_info=network_result)
    for result in (fetch_result, asset_result, resolve_result):
        if isinstance(result, BaseException):
            raise result
    assert not isinstance(asset_result, BaseException)
    assert not isinstance(resolve_result, BaseException)
    return PrepareObservationOutput(asset=asset_result, experiment_resolution=resolve_result)


async def _none() -> None:
    return None


@activity.defn
@track_activity()
def finalize_observation_activity(inputs: FinalizeObservationInputs) -> None:
    """Emit signals, persist the billed result, then run the fail-soft delivery steps and the Gemini cleanup.

    Only the result write raises, so a retry repeats the signal emission (each finding carries a
    deterministic idempotency key) but never a delivery step that ran after the write.
    """
    call_output = inputs.call_output
    signal_summaries: list[EmittedSignal] = []
    if call_output.signals:
        try:
            signal_summaries = emit_observation_signal_summaries_activity(
                EmitObservationSignalInputs(
                    team_id=inputs.team_id,
                    observation_id=inputs.observation_id,
                    exported_asset_id=inputs.exported_asset_id,
                    signals=call_output.signals,
                )
            )
        except Exception:
            # Signals are advisory and must never demote an otherwise successful observation.
            activity.logger.exception("replay_vision.signal_emission_failed")

    mark_observation_succeeded_activity(
        MarkObservationSucceededInputs(
            observation_id=inputs.observation_id,
            scanner_type=inputs.scanner_type,
            scanner_result=ScannerResult(
                model_output=call_output.model_output,
                signals_count=len(signal_summaries),
                signal_problem_types=[signal.problem_type for signal in signal_summaries],
                signal_summaries=signal_summaries,
                experiment_variant=inputs.experiment_variant,
                session_duration_s=inputs.session_duration_s,
            ),
        )
    )

    model_output = call_output.model_output
    _fail_soft(
        "event",
        lambda: emit_observation_event_activity(
            EmitObservationEventInputs(observation_id=inputs.observation_id, model_output=model_output)
        ),
    )
    if isinstance(model_output, BaseScannerOutput) and model_output.embedding_document() is not None:
        _fail_soft(
            "embed",
            lambda: embed_observation_activity(
                EmbedObservationInputs(
                    team_id=inputs.team_id,
                    session_id=inputs.session_id,
                    observation_id=inputs.observation_id,
                    scanner_id=inputs.scanner_id,
                    model_output=model_output,
                )
            ),
        )
    if isinstance(model_output, ClassifierOutput):
        _fail_soft(
            "tags",
            lambda: emit_classifier_tags_activity(
                EmitClassifierTagsInputs(
                    team_id=inputs.team_id,
                    session_id=inputs.session_id,
                    observation_id=inputs.observation_id,
                    classifier_output=model_output,
                )
            ),
        )
    if inputs.gemini_file_name:
        # The Gemini cleanup sweep deletes files that this step leaves behind.
        _fail_soft(
            "gemini_cleanup",
            lambda: cleanup_gemini_file_activity(CleanupGeminiFileInputs(gemini_file_name=inputs.gemini_file_name)),
            attempts=1,
        )


def _fail_soft(step: str, run: Callable[[], Awaitable[object]], attempts: int = _FAIL_SOFT_ATTEMPTS) -> None:
    async def call() -> None:
        await run()

    for attempt in range(1, attempts + 1):
        try:
            async_to_sync(call)()
            return
        except Exception:
            if attempt == attempts:
                activity.logger.exception("replay_vision.finalize_step_failed step=%s", step)
                return
            time.sleep(attempt)
