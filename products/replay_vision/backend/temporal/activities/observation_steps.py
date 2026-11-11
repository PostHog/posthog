"""Folded apply-scanner steps: Temporal bills each scheduled activity, so the cheap steps around the model call share one."""

import asyncio
from collections.abc import Awaitable, Callable

from temporalio import activity

from posthog.sync import database_sync_to_async

from products.replay_vision.backend.temporal.activities.cleanup_gemini_file import cleanup_gemini_file
from products.replay_vision.backend.temporal.activities.embed_observation import embed_observation
from products.replay_vision.backend.temporal.activities.emit_classifier_tags import emit_classifier_tags
from products.replay_vision.backend.temporal.activities.emit_observation_event import emit_observation_event
from products.replay_vision.backend.temporal.activities.emit_observation_signal import emit_observation_signal_summaries
from products.replay_vision.backend.temporal.activities.ensure_session_asset import ensure_session_asset
from products.replay_vision.backend.temporal.activities.fetch_session_events import fetch_session_events
from products.replay_vision.backend.temporal.activities.fetch_session_network import fetch_session_network
from products.replay_vision.backend.temporal.activities.observation_state import (
    mark_observation_running,
    mark_observation_succeeded,
)
from products.replay_vision.backend.temporal.activities.resolve_experiment_variant import resolve_experiment_variant
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.metrics import record_side_effect_failure
from products.replay_vision.backend.temporal.scanners.base import has_embeddable_text
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
    scanner_result,
)

# Attempts for each fail-soft delivery step. As separate activities these steps had their own retry policies,
# and a retry of the whole finalize activity would also repeat the steps that already succeeded.
_DELIVERY_ATTEMPTS = 3


@activity.defn
@track_activity()
async def prepare_observation_activity(inputs: PrepareObservationInputs) -> PrepareObservationOutput:
    """Mark the row running, then fetch the session's events, network and asset concurrently.

    Every step is safe to repeat, so a retry of this activity re-runs all of them.
    """
    observation_id, team_id, session_id = inputs.observation_id, inputs.team_id, inputs.session_id
    await database_sync_to_async(mark_observation_running)(MarkObservationRunningInputs(observation_id=observation_id))
    resolve: Awaitable[ResolveExperimentVariantOutput | None] = (
        resolve_experiment_variant(
            ResolveExperimentVariantInputs(observation_id=observation_id, team_id=team_id, session_id=session_id)
        )
        if inputs.resolve_experiment
        else _none()
    )
    # Every step runs to its end before an error is raised, so no step keeps running after the attempt fails.
    fetched, asset, network, resolution = await asyncio.gather(
        fetch_session_events(
            FetchSessionEventsInputs(observation_id=observation_id, team_id=team_id, session_id=session_id)
        ),
        ensure_session_asset(EnsureSessionAssetInputs(team_id=team_id, session_id=session_id)),
        fetch_session_network(
            FetchSessionNetworkInputs(observation_id=observation_id, team_id=team_id, session_id=session_id)
        ),
        resolve,
        return_exceptions=True,
    )
    if isinstance(network, BaseException):
        # The network capture is a side input that the scan can run without.
        activity.logger.warning("replay_vision.network_fetch_failed", exc_info=network)
    if isinstance(fetched, BaseException):
        raise fetched
    if isinstance(asset, BaseException):
        raise asset
    if isinstance(resolution, BaseException):
        raise resolution
    return PrepareObservationOutput(asset=asset, experiment_resolution=resolution)


async def _none() -> None:
    return None


@activity.defn
@track_activity()
async def finalize_observation_activity(inputs: FinalizeObservationInputs) -> None:
    """Emit signals, persist the billed result, then run the fail-soft delivery steps and the Gemini cleanup.

    Only the result write raises, so a retry repeats the signal emission (each finding carries a
    deterministic idempotency key) but never a delivery step that ran after the write.
    """
    call_output = inputs.call_output
    signal_summaries: list[EmittedSignal] = []
    if call_output.signals:
        # Signals are advisory, and the emitter already swallows and counts its own failures.
        signal_summaries = await database_sync_to_async(emit_observation_signal_summaries)(
            EmitObservationSignalInputs(
                team_id=inputs.team_id,
                observation_id=inputs.observation_id,
                exported_asset_id=inputs.exported_asset_id,
                signals=call_output.signals,
            )
        )

    await database_sync_to_async(mark_observation_succeeded)(
        MarkObservationSucceededInputs(
            observation_id=inputs.observation_id,
            scanner_type=inputs.scanner_type,
            scanner_result=scanner_result(call_output.model_output, signal_summaries, inputs.experiment_resolution),
        )
    )

    model_output = call_output.model_output
    deliveries: list[Awaitable[None]] = [
        _deliver(
            "event",
            lambda: emit_observation_event(
                EmitObservationEventInputs(observation_id=inputs.observation_id, model_output=model_output)
            ),
        )
    ]
    if has_embeddable_text(model_output):
        deliveries.append(
            _deliver(
                "embed",
                lambda: embed_observation(
                    EmbedObservationInputs(
                        team_id=inputs.team_id,
                        session_id=inputs.session_id,
                        observation_id=inputs.observation_id,
                        scanner_id=inputs.scanner_id,
                        model_output=model_output,
                    )
                ),
            )
        )
    if isinstance(model_output, ClassifierOutput):
        deliveries.append(
            _deliver(
                "tags",
                lambda: emit_classifier_tags(
                    EmitClassifierTagsInputs(
                        team_id=inputs.team_id,
                        session_id=inputs.session_id,
                        observation_id=inputs.observation_id,
                        classifier_output=model_output,
                    )
                ),
            )
        )
    if inputs.gemini_file_name:
        gemini_file_name = inputs.gemini_file_name
        # The Gemini cleanup sweep deletes files that this step leaves behind, so one attempt is enough.
        deliveries.append(
            _deliver(
                "gemini_cleanup",
                lambda: cleanup_gemini_file(CleanupGeminiFileInputs(gemini_file_name=gemini_file_name)),
                attempts=1,
            )
        )
    await asyncio.gather(*deliveries)


async def _deliver(step: str, run: Callable[[], Awaitable[None]], attempts: int = _DELIVERY_ATTEMPTS) -> None:
    for attempt in range(1, attempts + 1):
        try:
            await run()
            return
        except Exception:
            if attempt == attempts:
                record_side_effect_failure(step)
                activity.logger.exception("replay_vision.finalize_step_failed step=%s", step)
                return
            await asyncio.sleep(attempt)
