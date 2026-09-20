"""Retiring the stored object when an observation's media row goes away.

Expire, never delete: the asset row is the only pointer to the stored object, so the sweep
(`delete_expired_assets`) needs it to delete the object and then the row. Deleting the row here would
leak the object, which is how `ee/hogai/videos/session_moments.py` leaks today.

A receiver rather than a call at each deletion site: Django sends `post_delete` per instance for
cascaded and queryset deletes alike, so a retry, a scanner delete, a team delete, the Max tool and
anything added later are all covered without the caller knowing this exists.

The ids are collected and expired once per transaction, because a team delete cascades thousands of
rows through here and the asset rows it is about to delete anyway do not deserve an UPDATE each.
"""

import threading

from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.utils.timezone import now

from products.exports.backend.models.exported_asset import ExportedAsset
from products.replay_vision.backend.models.replay_observation_media import ReplayObservationMedia

_state = threading.local()


def _pending() -> dict[int, set[int]]:
    if not hasattr(_state, "asset_ids_by_team"):
        _state.asset_ids_by_team = {}
    return _state.asset_ids_by_team


def _expire_pending() -> None:
    by_team = _pending()
    _state.asset_ids_by_team = {}
    for team_id, asset_ids in by_team.items():
        # Filtered rather than saved, so the sweep's own asset delete cascades here and matches nothing.
        ExportedAsset.objects.filter(pk__in=asset_ids, team_id=team_id, expires_after__gt=now()).update(
            expires_after=now()
        )


@receiver(post_delete, sender=ReplayObservationMedia)
def expire_media_asset(
    sender: type[ReplayObservationMedia], instance: ReplayObservationMedia, **kwargs: object
) -> None:
    by_team = _pending()
    first = not by_team
    by_team.setdefault(instance.team_id, set()).add(instance.asset_id)
    if first:
        # Outside an atomic block Django runs this at once, which keeps a lone delete a single UPDATE.
        transaction.on_commit(_expire_pending)
