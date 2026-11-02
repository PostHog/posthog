"""Per-user counts of how often the Highlights feed showed each observation."""

from collections.abc import Sequence
from datetime import datetime
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
        ReplayObservationFeedImpression.objects.for_team(team_id).filter(
            user_id=user_id, observation_id__in=observation_ids
        ).exclude(last_feed_load_id=feed_load_id).update(
            shown_count=F("shown_count") + 1, last_shown_at=now, last_feed_load_id=feed_load_id
        )
        # Rows that exist were counted above, so the conflict only skips them. A concurrent first
        # impression from another tab wins the race the same way, which is harmless.
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
            ],
            ignore_conflicts=True,
        )


def feed_impression_counts(
    *, team_id: int, user_id: int, observation_ids: Sequence[UUID], as_of: datetime
) -> dict[UUID, int]:
    """Times each observation was shown to the user as of `as_of`.

    A row shown again since `as_of` counts one less, which covers the load being paged, so its own
    impressions do not shift its later pages.
    """
    if not observation_ids:
        return {}
    rows = (
        ReplayObservationFeedImpression.objects.for_team(team_id)
        .filter(user_id=user_id, observation_id__in=observation_ids)
        .values_list("observation_id", "shown_count", "last_shown_at")
    )
    counts: dict[UUID, int] = {}
    for observation_id, shown_count, last_shown_at in rows:
        count = shown_count - 1 if last_shown_at > as_of else shown_count
        if count > 0:
            counts[observation_id] = count
    return counts
