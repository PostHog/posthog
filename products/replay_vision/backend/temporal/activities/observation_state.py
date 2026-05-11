from uuid import UUID

from django.db import IntegrityError
from django.utils import timezone

import temporalio.activity
from temporalio.exceptions import ApplicationError

from posthog.sync import database_sync_to_async

from products.replay_vision.backend.models.replay_lens import ReplayLens
from products.replay_vision.backend.models.replay_observation import ObservationStatus, ReplayObservation


@temporalio.activity.defn
async def create_observation_activity(
    lens_id: UUID,
    session_id: str,
    triggered_by: str,
    triggered_by_user_id: int | None,
    workflow_id: str,
) -> UUID:
    """Create the observation row in `running` status. Duplicate (lens, session) → non-retryable ApplicationError."""

    @database_sync_to_async
    def _create() -> UUID:
        lens = ReplayLens.objects.get(id=lens_id)
        try:
            observation = ReplayObservation.objects.create(
                lens=lens,
                session_id=session_id,
                lens_version=lens.lens_version,
                lens_config_snapshot=lens.lens_config,
                triggered_by=triggered_by,
                triggered_by_user_id=triggered_by_user_id,
                status=ObservationStatus.RUNNING,
                started_at=timezone.now(),
                workflow_id=workflow_id,
            )
        except IntegrityError as e:
            if "replay_observation_unique_lens_session" in str(e):
                raise ApplicationError(
                    f"Observation for lens {lens_id} on session {session_id} already exists",
                    non_retryable=True,
                )
            raise
        return observation.id

    return await _create()


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
