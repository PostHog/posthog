"""Per-user counts of how often What to watch showed each observation."""

from collections.abc import Sequence
from uuid import UUID

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from products.replay_vision.backend.models.replay_observation_feed_impression import ReplayObservationFeedImpression


def record_feed_impressions(*, team_id: int, user_id: int, observation_ids: Sequence[UUID], feed_load_id: UUID) -> None:
    """Count one impression per observation per feed load; a repeat from the same load changes nothing."""
    if not observation_ids:
        return
    now = timezone.now()
    with transaction.atomic():
        existing = ReplayObservationFeedImpression.objects.for_team(team_id).filter(
            user_id=user_id, observation_id__in=observation_ids
        )
        existing_ids = set(existing.values_list("observation_id", flat=True))
        existing.exclude(last_feed_load_id=feed_load_id).update(
            shown_count=F("shown_count") + 1, last_shown_at=now, last_feed_load_id=feed_load_id
        )
        # A concurrent first impression from another tab wins the race and this one is dropped, which is harmless.
        ReplayObservationFeedImpression.objects.bulk_create(
            [
                ReplayObservationFeedImpression(
                    team_id=team_id,
                    user_id=user_id,
                    observation_id=observation_id,
                    last_shown_at=now,
                    last_feed_load_id=feed_load_id,
                )
                for observation_id in observation_ids
                if observation_id not in existing_ids
            ],
            ignore_conflicts=True,
        )


def feed_impression_counts(
    *, team_id: int, user_id: int, observation_ids: Sequence[UUID], feed_load_id: UUID | None
) -> dict[UUID, int]:
    """Times each observation was shown to the user, not counting the load in `feed_load_id`."""
    if not observation_ids:
        return {}
    rows = (
        ReplayObservationFeedImpression.objects.for_team(team_id)
        .filter(user_id=user_id, observation_id__in=observation_ids)
        .values_list("observation_id", "shown_count", "last_feed_load_id")
    )
    counts: dict[UUID, int] = {}
    for observation_id, shown_count, last_feed_load_id in rows:
        count = shown_count - 1 if feed_load_id is not None and last_feed_load_id == feed_load_id else shown_count
        if count > 0:
            counts[observation_id] = count
    return counts
