import json
from uuid import UUID

from django.utils import timezone

import temporalio.activity
from asgiref.sync import sync_to_async

from posthog.cdp.internal_events import InternalEventEvent, produce_internal_event
from posthog.sync import database_sync_to_async

from products.replay_vision.backend.models.replay_lens import ReplayLens
from products.replay_vision.backend.models.replay_observation import ObservationStatus, ReplayObservation
from products.replay_vision.backend.temporal.types import FinalLensOutput

REPLAY_LENS_EVENT = "$replay_lens"


@temporalio.activity.defn
async def emit_lens_event_and_mark_succeeded_activity(
    observation_id: UUID,
    lens_id: UUID,
    session_id: str,
    final: FinalLensOutput,
) -> None:
    @database_sync_to_async
    def _load() -> tuple[ReplayLens, ReplayObservation]:
        observation = ReplayObservation.objects.select_related("lens").get(id=observation_id)
        return observation.lens, observation

    lens, observation = await _load()
    result = json.loads(final.output_json)

    properties = {
        "$session_id": session_id,
        "$replay_lens_id": str(lens.id),
        "$replay_lens_name": lens.name,
        "$replay_lens_type": lens.lens_type,
        "$replay_lens_version": observation.lens_version,
        "$replay_observation_id": str(observation_id),
        "$replay_lens_provider": lens.provider,
        "$replay_lens_model": lens.model,
        "$replay_lens_confidence": final.confidence,
        "$replay_lens_result": result,
    }

    await sync_to_async(produce_internal_event, thread_sensitive=False)(
        team_id=lens.team_id,
        event=InternalEventEvent(
            event=REPLAY_LENS_EVENT,
            distinct_id=session_id,
            properties=properties,
        ),
    )

    @database_sync_to_async
    def _mark_succeeded() -> None:
        ReplayObservation.objects.filter(id=observation_id).update(
            status=ObservationStatus.SUCCEEDED,
            completed_at=timezone.now(),
            model_used=lens.model,
            provider_used=lens.provider,
        )

    await _mark_succeeded()
