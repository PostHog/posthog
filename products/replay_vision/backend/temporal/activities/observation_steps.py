"""Folded apply-scanner steps: Temporal bills each scheduled activity, so the cheap steps around the model call share one."""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, ParamSpec, TypeVar

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
from products.replay_vision.backend.temporal.errors import IneligibleSessionError
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
# The per-attempt limits the separate activities had as their start_to_close timeouts.
_DELIVERY_ATTEMPT_TIMEOUT_SECONDS = 30
_SIGNAL_EMISSION_TIMEOUT_SECONDS = 120
# Under prepare's own start_to_close timeout, so a stalled network capture is dropped instead of failing the scan.
_NETWORK_FETCH_TIMEOUT_SECONDS = 90

_P = ParamSpec("_P")
_R = TypeVar("_R")


@activity.defn
@track_activity()
async def prepare_observation_activity(inputs: PrepareObservationInputs) -> PrepareObservationOutput:
    """Mark the row running, then fetch the session's events, network and asset concurrently.

    Every step is safe to repeat, so a retry of this activity re-runs all of them.
    """
    observation_id, team_id, session_id = inputs.observation_id, inputs.team_id, inputs.session_id
    await _off_thread(mark_observation_running)(MarkObservationRunningInputs(observation_id=observation_id))
    resolve: Awaitable[ResolveExperimentVariantOutput | None] = (
        resolve_experiment_variant(
            ResolveExperimentVariantInputs(observation_id=observation_id, team_id=team_id, session_id=session_id)
        )
        if inputs.resolve_experiment
        else _none()
    )
    steps = [
        asyncio.ensure_future(
            fetch_session_events(
                FetchSessionEventsInputs(observation_id=observation_id, team_id=team_id, session_id=session_id)
            )
        ),
        asyncio.ensure_future(ensure_session_asset(EnsureSessionAssetInputs(team_id=team_id, session_id=session_id))),
        asyncio.ensure_future(
            asyncio.wait_for(
                fetch_session_network(
                    FetchSessionNetworkInputs(observation_id=observation_id, team_id=team_id, session_id=session_id)
                ),
                _NETWORK_FETCH_TIMEOUT_SECONDS,
            )
        ),
        asyncio.ensure_future(resolve),
    ]
    # The network capture is left out: any error from it, ineligible included, is absorbed below.
    await _raise_ineligible_early([steps[0], steps[1], steps[3]])
    # Other errors wait for every step to end, so no step keeps running after the attempt fails.
    fetched, asset, network, resolution = await asyncio.gather(*steps, return_exceptions=True)
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


async def _raise_ineligible_early(steps: Sequence[asyncio.Future[Any]]) -> None:
    """An ineligible session is final, so raise it as soon as any step reports it and cancel the rest.

    Waiting for a stalled sibling would run the attempt into its timeout, and the retries would end the
    observation as failed instead of ineligible.
    """
    pending = set(steps)
    while pending:
        done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_EXCEPTION)
        ineligible = next(
            (
                step.exception()
                for step in done
                if not step.cancelled() and isinstance(step.exception(), IneligibleSessionError)
            ),
            None,
        )
        if ineligible is not None:
            for step in pending:
                step.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            raise ineligible


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
        # Signals are advisory, and the emitter already swallows and counts its own failures. The time limit
        # keeps a stalled emission from using up the activity before the billed result is written.
        try:
            signal_summaries = await asyncio.wait_for(
                _off_thread(emit_observation_signal_summaries)(
                    EmitObservationSignalInputs(
                        team_id=inputs.team_id,
                        observation_id=inputs.observation_id,
                        exported_asset_id=inputs.exported_asset_id,
                        signals=call_output.signals,
                    )
                ),
                _SIGNAL_EMISSION_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            record_side_effect_failure("signal")
            activity.logger.warning("replay_vision.signal_emission_timed_out")

    await _off_thread(mark_observation_succeeded)(
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


def _off_thread(fn: Callable[_P, _R]) -> Callable[_P, Awaitable[_R]]:
    # Not thread-sensitive, so these ORM calls do not queue behind every other activity's on the worker's one sync thread.
    return database_sync_to_async(fn, thread_sensitive=False)


async def _deliver(step: str, run: Callable[[], Awaitable[None]], attempts: int = _DELIVERY_ATTEMPTS) -> None:
    for attempt in range(1, attempts + 1):
        try:
            # A hung call must not run finalize into its timeout after the result is already saved.
            await asyncio.wait_for(run(), _DELIVERY_ATTEMPT_TIMEOUT_SECONDS)
            return
        except Exception:
            if attempt == attempts:
                record_side_effect_failure(step)
                activity.logger.exception("replay_vision.finalize_step_failed step=%s", step)
                return
            await asyncio.sleep(attempt)
