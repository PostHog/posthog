from uuid import UUID

from django.utils import timezone

import temporalio.activity

from posthog.sync import database_sync_to_async

from products.replay_vision.backend.models.replay_observation import ObservationStatus, ReplayObservation


@temporalio.activity.defn
async def mark_observation_running_activity(observation_id: UUID, workflow_id: str) -> None:
    @database_sync_to_async
    def _update() -> None:
        ReplayObservation.objects.filter(id=observation_id).update(
            status=ObservationStatus.RUNNING,
            workflow_id=workflow_id,
        )

    await _update()


@temporalio.activity.defn
async def mark_observation_failed_activity(observation_id: UUID, error_reason: str) -> None:
    @database_sync_to_async
    def _update() -> None:
        ReplayObservation.objects.filter(id=observation_id).update(
            status=ObservationStatus.FAILED,
            error_reason=error_reason,
            completed_at=timezone.now(),
        )

    await _update()
