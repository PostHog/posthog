"""Retiring the stored object when an observation's media row goes away.

Expire, never delete: the asset row is the only pointer to the stored object, so the sweep
(`delete_expired_assets`) needs it to delete the object and then the row. Deleting the row here would
leak the object, which is how `ee/hogai/videos/session_moments.py` leaks today.

A receiver rather than a call at each deletion site: Django sends `post_delete` per instance for
cascaded and queryset deletes alike, so a retry, a scanner delete, a team delete, the Max tool and
anything added later are all covered without the caller knowing this exists.
"""

from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.utils.timezone import now

from products.exports.backend.models.exported_asset import ExportedAsset
from products.replay_vision.backend.models.replay_observation_media import ReplayObservationMedia


@receiver(post_delete, sender=ReplayObservationMedia)
def expire_media_asset(
    sender: type[ReplayObservationMedia], instance: ReplayObservationMedia, **kwargs: object
) -> None:
    # Filtered rather than saved, so the sweep's own asset delete cascades here and matches nothing.
    ExportedAsset.objects.filter(pk=instance.asset_id, team_id=instance.team_id, expires_after__gt=now()).update(
        expires_after=now()
    )
