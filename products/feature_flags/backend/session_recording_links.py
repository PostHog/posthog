"""Keeps `Team.session_recording_linked_flag` in step with the flag key it points at.

The stored dict carries both the flag `id` and its `key`, but the SDK payload that
`RemoteConfig._build_session_recording_config` builds is derived from the key alone. Both the
browser and React Native SDKs treat a linked flag they can't resolve as "do not record", so a
stale key silently turns replay off for the team rather than surfacing an error anywhere.
"""

from collections.abc import Collection
from typing import Any

from django.db import transaction
from django.db.models import QuerySet

import structlog

from posthog.exceptions_capture import capture_exception
from posthog.models import Team
from posthog.models.signals import model_activity_signal, mutable_receiver

from products.feature_flags.backend.models.feature_flag import FeatureFlag

logger = structlog.get_logger(__name__)

REPLAY_LINKED_FLAG_DELETE_ERROR = (
    "This feature flag is used in session replay settings. Please remove it from replay settings before deleting."
)


def teams_linking_flag(feature_flag: FeatureFlag) -> QuerySet[Team]:
    """Every team gating session recording on this flag."""
    # Scoped by project rather than by team: any team in the project can gate recording on a flag
    # owned by a sibling team.
    return Team.objects.filter(
        project_id=feature_flag.team.project_id,
        session_recording_linked_flag__contains={"id": feature_flag.id},
    )


def replay_linked_flag_ids(project_id: int, flag_ids: Collection[int]) -> set[int]:
    """Which of the given flags a team in this project gates session recording on.

    The batch equivalent of `teams_linking_flag`, in one query. Matching ids inside jsonb keeps
    that check's comparison semantics, so the single-flag and bulk delete guards agree on what
    counts as linked; a malformed value like `{"id": true}` matches no flag, because jsonb never
    equates booleans with numbers.
    """
    if not flag_ids:
        return set()
    stored_ids = Team.objects.filter(
        project_id=project_id,
        session_recording_linked_flag__id__in=flag_ids,
    ).values_list("session_recording_linked_flag__id", flat=True)
    # jsonb also equates numbers regardless of representation, so a stored float id can match an
    # int flag id; normalize for the int membership checks callers do.
    return {int(stored_id) for stored_id in stored_ids}


def update_linked_flag_key(team: Team, expected_flag_id: int, new_key: str) -> None:
    """Rewrite the stored key on a team's replay link, leaving teams that no longer need it alone."""
    # Locks the row and re-reads inside the lock, rather than trusting `team`'s in-memory copy:
    # callers load teams in a batch before looping over them, so another edit to this team's
    # linked flag could land before its turn comes up. The lock closes the window between the
    # read and the save below; taking it here is safe because it's the only row this function
    # locks and the transaction commits before returning, so it can't deadlock against another
    # call doing the same for a different team (see `relink_teams_on_key_change` for the case
    # that does require avoiding a lock).
    with transaction.atomic():
        linked_flag = (
            Team.objects.select_for_update()
            .filter(pk=team.pk)
            .values_list("session_recording_linked_flag", flat=True)
            .first()
        )
        if not isinstance(linked_flag, dict) or linked_flag.get("id") != expected_flag_id:
            # Someone pointed the team at a different flag since the caller looked it up; that
            # edit isn't ours to touch, and this rename has nothing left to fix here.
            return
        if linked_flag.get("key") == new_key:
            # A no-op save would still spend a write, a Celery task, and a RemoteConfig rebuild.
            return

        team.session_recording_linked_flag = {**linked_flag, "key": new_key}
        # Saving the instance rather than issuing a queryset `update()` is what fires the `post_save`
        # receiver that refreshes the team's RemoteConfig; a bulk update would leave the cached SDK
        # payload holding the old key.
        team.save(update_fields=["session_recording_linked_flag"])


def relink_teams(feature_flag: FeatureFlag) -> None:
    """Point every team gating replay on this flag at its current key."""
    # Reads the key fresh rather than trusting feature_flag.key from the signal: two renames of
    # the same flag committed close together fire their on_commit callbacks with no ordering
    # guarantee between them, and update_linked_flag_key's guard only checks the flag id and
    # whether the key differs - not which rename is newer. A stale callback that reads its key
    # from memory can overwrite a team a later rename's callback already brought up to date. This
    # re-read makes every callback converge on whatever key is actually stored, regardless of
    # which rename triggered it or the order the callbacks run in.
    current_key = (
        FeatureFlag.objects_including_soft_deleted.filter(pk=feature_flag.pk).values_list("key", flat=True).first()
    )
    if current_key is None:
        # The row is gone entirely, not just soft-deleted; repair_replay_linked_flag_keys reports
        # these teams as flag_missing on its next run.
        return

    for team in teams_linking_flag(feature_flag):
        try:
            update_linked_flag_key(team, feature_flag.id, current_key)
        except Exception:
            # This runs after the rename has committed, so raising would fail a request that
            # already succeeded, and the retry would find the key unchanged and skip the relink
            # entirely. Report instead and leave the row for `repair_replay_linked_flag_keys`.
            # Per team, so one unwritable row doesn't strand the others.
            logger.exception("replay_relink_failed", flag_id=feature_flag.pk, team_id=team.pk)
            capture_exception()


@mutable_receiver(model_activity_signal, sender=FeatureFlag)
def relink_teams_on_key_change(
    sender: Any, before_update: FeatureFlag | None, after_update: FeatureFlag | None, **kwargs: Any
) -> None:
    # Wired to the model signal rather than to FeatureFlagSerializer so renames from the Django
    # admin, a shell, or a Celery task keep the link intact too. `before_update` is None on create;
    # `after_update` is None on delete.
    if before_update is None or after_update is None or before_update.key == after_update.key:
        return

    # Unlike `repair_replay_linked_flag_keys`, this has no `after_update.deleted` guard, including
    # for the tombstone rename `_free_key_held_by_soft_deleted_flags` does when freeing a
    # soft-deleted flag's key for reuse. That's intentional: relinking still rewrites a team's
    # stored key to the flag's new, id-suffixed tombstone, which no live flag's key can equal.
    # Skipping the rewrite would leave the team pointing at the now-freed original key, which a
    # new flag could reuse next, silently gating replay on a flag the team never linked.

    # Deferred to commit because the serializer renames inside a transaction that holds
    # `select_for_update` on the flag row, and taking team locks in that window invites deadlocks.
    # Outside a transaction (admin, shell) `on_commit` runs the callback immediately.
    transaction.on_commit(lambda: relink_teams(after_update))
