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
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

import structlog

from posthog.exceptions_capture import capture_exception
from posthog.models import Team

from products.feature_flags.backend.field_snapshots import capture_fields_before_save, snapshot_if_changed
from products.feature_flags.backend.models.feature_flag import FeatureFlag

logger = structlog.get_logger(__name__)

REPLAY_LINKED_FLAG_DELETE_ERROR = (
    "This feature flag is used in session replay settings. Please remove it from replay settings before deleting."
)


def linked_flag_id(linked_flag: Any) -> int | None:
    """The flag id a stored replay link points at, or None when it holds no usable one."""
    if not isinstance(linked_flag, dict):
        return None
    stored_id = linked_flag.get("id")
    # The column is schemaless, so anything an API client or the admin's JSON widget sent can be
    # here. Only an int is usable, and every other shape is left for the caller to handle rather
    # than coerced. `bool` is excluded explicitly because it subclasses `int`, so `{"id": true}`
    # would otherwise read as a link to flag 1.
    if isinstance(stored_id, bool) or not isinstance(stored_id, int):
        return None
    return stored_id


def teams_linking_flag(feature_flag: FeatureFlag) -> QuerySet[Team]:
    """Every team gating session recording on this flag."""
    return teams_linking_flag_in_project(feature_flag.team.project_id, feature_flag.id)


def teams_linking_flag_in_project(project_id: int, flag_id: int) -> QuerySet[Team]:
    """Every team in this project gating session recording on the flag with this id."""
    # Scoped by project rather than by team: any team in the project can gate recording on a flag
    # owned by a sibling team.
    return Team.objects.filter(
        project_id=project_id,
        session_recording_linked_flag__contains={"id": flag_id},
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
        # Don't route this through `linked_flag_id`: it stays loose to match the jsonb comparison
        # `teams_linking_flag` selected on, where a stored float id equals an int one.
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


_KEY_BEFORE_SAVE_ATTR = "_replay_link_key_before_save"


@receiver(pre_save, sender=FeatureFlag)
def capture_replay_link_key_before_save(
    sender: type[FeatureFlag],
    instance: FeatureFlag,
    raw: bool = False,
    update_fields: frozenset[str] | None = None,
    **kwargs: Any,
) -> None:
    # Its own snapshot rather than sharing the one `flag_version_sync` takes: relinking must
    # not hinge on which fields another feature happens to watch.
    # objects_including_soft_deleted so the tombstone rename a soft-deleted flag gets when
    # `_free_key_held_by_soft_deleted_flags` frees its key for reuse is captured too.
    capture_fields_before_save(
        instance,
        FeatureFlag.objects_including_soft_deleted,
        frozenset({"key"}),
        attr=_KEY_BEFORE_SAVE_ATTR,
        update_fields=update_fields,
        raw=raw,
    )


@receiver(post_save, sender=FeatureFlag)
def relink_teams_on_key_change(
    sender: type[FeatureFlag],
    instance: FeatureFlag,
    created: bool = False,
    raw: bool = False,
    **kwargs: Any,
) -> None:
    # Wired to plain model signals rather than to FeatureFlagSerializer so renames from the
    # Django admin, a shell, or a Celery task keep the link intact too, and rather than to
    # model_activity_signal because activity logging is tunable in ways recording must not
    # inherit: `mute_selected_signals()` and the activity-log `signal_exclusions` can both
    # silently drop that signal, and a skipped relink turns replay off for every linking team.
    # The snapshot is only a change detector; `relink_teams` re-reads the stored key itself.
    if raw or created or snapshot_if_changed(instance, attr=_KEY_BEFORE_SAVE_ATTR) is None:
        return

    # Unlike `repair_replay_linked_flag_keys`, this has no `instance.deleted` guard, including
    # for the tombstone rename `_free_key_held_by_soft_deleted_flags` does when freeing a
    # soft-deleted flag's key for reuse. That's intentional: relinking still rewrites a team's
    # stored key to the flag's new, id-suffixed tombstone, which no live flag's key can equal.
    # Skipping the rewrite would leave the team pointing at the now-freed original key, which a
    # new flag could reuse next, silently gating replay on a flag the team never linked.

    # Deferred to commit because the serializer renames inside a transaction that holds
    # `select_for_update` on the flag row, and taking team locks in that window invites deadlocks.
    # Outside a transaction (admin, shell) `on_commit` runs the callback immediately.
    transaction.on_commit(lambda: relink_teams(instance))
