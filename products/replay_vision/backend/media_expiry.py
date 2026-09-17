"""Retiring the media objects of observations that are going away.

Expire, never delete: the asset row is the only pointer to the stored object, so the expiry sweep
(`delete_expired_assets`) needs it to delete the object and then the row. Deleting the row here would
leak the object, which is how `ee/hogai/videos/session_moments.py` leaks today.
"""

from collections.abc import Iterable
from uuid import UUID

from django.db.models import QuerySet
from django.utils.timezone import now

from products.exports.backend.models.exported_asset import ExportedAsset

# Bounds the `IN` list, because a scanner can own tens of thousands of observations.
_BATCH_SIZE = 500


def expire_media_for_observations(team_id: int, observation_ids: Iterable[UUID]) -> int:
    """Mark every media asset of these observations as expired, so the next sweep deletes object and row."""
    expired = 0
    batch: list[str] = []
    for observation_id in observation_ids:
        batch.append(str(observation_id))
        if len(batch) >= _BATCH_SIZE:
            expired += _expire_batch(team_id, batch)
            batch = []
    if batch:
        expired += _expire_batch(team_id, batch)
    return expired


def expire_media_for_scanner(team_id: int, observations: QuerySet) -> int:
    """Same, for every observation a scanner owns."""
    return expire_media_for_observations(team_id, observations.values_list("id", flat=True).iterator())


def _expire_batch(team_id: int, observation_ids: list[str]) -> int:
    return ExportedAsset.objects.filter(
        team_id=team_id,
        export_context__observation_id__in=observation_ids,
    ).update(expires_after=now())
