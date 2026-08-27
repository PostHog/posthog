"""Keeps a team's session replay recording gate in step with the flag key it points at.

A team can gate recording on a flag in two columns. `Team.session_recording_linked_flag` stores the
flag `id` alongside its `key`. Each V2 trigger group in `Team.session_recording_trigger_groups`
stores an optional `conditions.flag`, holding either a bare key string or an object carrying the
same `id`/`key`/`variant` shape. The SDK payload that `RemoteConfig._build_session_recording_config`
builds resolves both by key alone, and both the browser and React Native SDKs treat a flag they
can't resolve as "do not record", so a stale key silently turns replay off for the team rather than
surfacing an error anywhere.

The replay settings UI writes the bare string form, so a reference usually has no id to match on.
Flag keys are unique within a project, so a key alone identifies one flag there, which is why every
matcher here is project-scoped.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from django.db import transaction
from django.db.models import Q, QuerySet
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


@dataclass(frozen=True, kw_only=True)
class TriggerGroupFlagRef:
    """One trigger group's reference to a feature flag, and where in the stored config it sits."""

    group_index: int
    stored_flag: Any
    key: str | None
    flag_id: int | None


@dataclass(frozen=True, kw_only=True)
class ReplayGateRewrite:
    """New values for a team's gate columns. `None` leaves that column alone."""

    linked_flag: dict[str, Any] | None = None
    trigger_groups: dict[str, Any] | None = None


@dataclass(frozen=True, kw_only=True)
class ReplayFlagGates:
    """Which flags a project's teams gate recording on, keyed the way each column stores it."""

    flag_ids: frozenset[int]
    flag_keys: frozenset[str]

    def gates(self, feature_flag: FeatureFlag) -> bool:
        return feature_flag.id in self.flag_ids or feature_flag.key in self.flag_keys

    def as_q(self) -> Q:
        """`gates` as a queryset predicate, for annotating a page of flags in one go.

        Sorted so the `IN` lists keep a stable order: set iteration order varies per process,
        which would churn query snapshots.
        """
        return Q(id__in=sorted(self.flag_ids)) | Q(key__in=sorted(self.flag_keys))


def stored_flag_id(stored_flag: Any) -> int | None:
    """The flag id a stored replay reference points at, or None when it holds no usable one.

    Covers both columns: `session_recording_linked_flag` and the object form of a trigger group's
    `conditions.flag` share a shape.
    """
    if not isinstance(stored_flag, dict):
        return None
    flag_id = stored_flag.get("id")
    # The column is schemaless, so anything an API client or the admin's JSON widget sent can be
    # here. `bool` is excluded explicitly because it subclasses `int`, so `{"id": true}` would
    # otherwise read as a link to flag 1.
    if isinstance(flag_id, bool):
        return None
    if isinstance(flag_id, int):
        return flag_id
    # Postgres compares JSON numbers numerically, so a stored `7.0` satisfies the `{"id": 7}`
    # containment probe. Reading it the same way here keeps the SQL matcher and the Python scan
    # from answering differently for the same team.
    if isinstance(flag_id, float) and flag_id.is_integer():
        return int(flag_id)
    return None


def _trigger_group_flag_key(stored_flag: Any) -> str | None:
    """The flag key a trigger group's `conditions.flag` names, in either stored shape."""
    if isinstance(stored_flag, str):
        return stored_flag or None
    if isinstance(stored_flag, dict):
        key = stored_flag.get("key")
        return key if isinstance(key, str) and key else None
    return None


def trigger_group_flag_refs(trigger_groups: Any) -> list[TriggerGroupFlagRef]:
    """Every `conditions.flag` reference in a team's stored trigger groups.

    Empty for a column that gates on no flag and for one too malformed to read, since neither holds
    a reference to act on.
    """
    if not isinstance(trigger_groups, dict) or not isinstance(trigger_groups.get("groups"), list):
        return []

    groups = trigger_groups["groups"]
    refs = []
    for index, group in enumerate(groups):
        conditions = group.get("conditions") if isinstance(group, dict) else None
        stored_flag = conditions.get("flag") if isinstance(conditions, dict) else None
        if stored_flag is None:
            continue
        refs.append(
            TriggerGroupFlagRef(
                group_index=index,
                stored_flag=stored_flag,
                key=_trigger_group_flag_key(stored_flag),
                flag_id=stored_flag_id(stored_flag),
            )
        )
    return refs


def _trigger_group_flag_probe(stored_flag: Any) -> dict[str, Any]:
    """A JSONB containment probe matching a trigger group whose `conditions.flag` is `stored_flag`.

    Containment reaches a group at any index in the array and never casts, so a malformed stored
    shape yields False rather than erroring the query. A probe for the bare string form never
    matches the object form, or the reverse, so a caller that wants both sends both.
    """
    return {"groups": [{"conditions": {"flag": stored_flag}}]}


def teams_gating_replay_on_flag(feature_flag: FeatureFlag, *, key: str) -> QuerySet[Team]:
    """Every team gating session recording on this flag, through either column.

    `key` is separate from `feature_flag.key` so the relink can find teams by the key they still
    hold, which is the one the flag has just stopped having.
    """
    # Scoped by project rather than by team: any team in the project can gate recording on a flag
    # owned by a sibling team.
    return Team.objects.filter(
        Q(session_recording_linked_flag__contains={"id": feature_flag.id})
        | Q(session_recording_trigger_groups__contains=_trigger_group_flag_probe(key))
        | Q(session_recording_trigger_groups__contains=_trigger_group_flag_probe({"key": key}))
        # An object reference holding a key the flag no longer has still names it by id. Matching
        # that too is what stops a delete stranding a reference the repair command could have
        # fixed, since deleting the flag takes away the only record of what the key meant.
        | Q(session_recording_trigger_groups__contains=_trigger_group_flag_probe({"id": feature_flag.id})),
        project_id=feature_flag.team.project_id,
    )


def teams_linking_flag_in_project(project_id: int, flag_id: int) -> QuerySet[Team]:
    """Every team in this project whose linked flag column points at the flag with this id.

    Reads the linked flag column only, unlike `teams_gating_replay_on_flag`, so a team gating on
    a trigger group is not returned. Its one caller frees a soft-deleted flag's key for reuse, and
    a trigger group naming that flag by id alone would go unseen there.
    """
    return Team.objects.filter(
        project_id=project_id,
        session_recording_linked_flag__contains={"id": flag_id},
    )


def replay_gated_flags(project_id: int) -> ReplayFlagGates:
    """Every flag a team in this project gates session recording on, from both columns.

    One query for the whole project, for callers checking many flags at once;
    `teams_gating_replay_on_flag` is the per-flag equivalent. Matching trigger groups by key is
    unambiguous here because both this scan and the flags its result is tested against are scoped
    to the one project.
    """
    stored = Team.objects.filter(
        Q(session_recording_linked_flag__isnull=False) | Q(session_recording_trigger_groups__isnull=False),
        project_id=project_id,
    ).values_list("session_recording_linked_flag", "session_recording_trigger_groups")

    flag_ids: set[int] = set()
    flag_keys: set[str] = set()
    for linked_flag, trigger_groups in stored:
        if (flag_id := stored_flag_id(linked_flag)) is not None:
            flag_ids.add(flag_id)
        for ref in trigger_group_flag_refs(trigger_groups):
            if ref.key is not None:
                flag_keys.add(ref.key)
            if ref.flag_id is not None:
                flag_ids.add(ref.flag_id)
    return ReplayFlagGates(flag_ids=frozenset(flag_ids), flag_keys=frozenset(flag_keys))


def rewritten_linked_flag(linked_flag: Any, *, flag_id: int, new_key: str) -> dict[str, Any] | None:
    """A team's replay link with its key rewritten, or None when there is nothing to change."""
    if stored_flag_id(linked_flag) != flag_id:
        # Team selection matches either column, so a team can be in hand because of its trigger
        # groups while this one points at an unrelated flag. Rewriting it then would gate that
        # team's recording on a key the flag it names never had.
        return None
    if linked_flag.get("key") == new_key:
        return None
    return {**linked_flag, "key": new_key}


def rewritten_trigger_groups(trigger_groups: Any, renames: Mapping[int, str]) -> dict[str, Any] | None:
    """A team's named trigger groups with their flag keys rewritten, or None when nothing changes.

    Keyed by group index, so which references move stays the decision of the caller that
    classified them. Keying by flag key instead would drag in every other group holding the same
    one, including references the caller deliberately left alone, and would collapse two groups
    naming one stale key onto whichever flag was resolved first.

    RemoteConfig hands these groups to the SDK nearly verbatim, so a rewrite that dropped
    `sampleRate`, `urls`, or the group id would break the gate outright rather than merely
    mistarget it. Every reference therefore keeps the shape it was stored in.
    """
    refs = trigger_group_flag_refs(trigger_groups)
    if not refs:
        return None

    # Driven off the refs rather than off `renames` directly: a ref exists only for a group that
    # holds a `conditions.flag`, so an index naming a group without one cannot reach the rewrite.
    groups = list(trigger_groups["groups"])
    changed = False
    for ref in refs:
        new_key = renames.get(ref.group_index)
        if new_key is None or new_key == ref.key:
            continue
        group = groups[ref.group_index]
        rewritten = new_key if isinstance(ref.stored_flag, str) else {**ref.stored_flag, "key": new_key}
        groups[ref.group_index] = {**group, "conditions": {**group["conditions"], "flag": rewritten}}
        changed = True
    return {**trigger_groups, "groups": groups} if changed else None


def save_replay_gate_rewrites(team_id: int, compute: Callable[[Team], ReplayGateRewrite]) -> None:
    """Rewrite a team's gate columns under a row lock, in a single save.

    `compute` is handed the team as it exists inside the lock rather than a copy the caller read
    earlier. Callers load their teams in one batch and then loop, so an admin edit to this team's
    replay settings can land before its turn comes up, and both rewrites replace a whole column —
    computing one from a stale copy would put the pre-edit column back and publish it to the SDKs.

    Taking the lock here is safe because this is the only row the function locks and the
    transaction commits before returning, so two calls for different teams cannot deadlock against
    each other. `relink_teams_on_key_change` defers to `on_commit` so the serializer's lock on the
    flag row is already released by the time this runs.
    """
    with transaction.atomic():
        # Loads every column rather than deferring: the `post_save` cache receiver reads about
        # thirty other fields, each its own query when deferred.
        team = Team.objects.select_for_update().filter(pk=team_id).first()
        if team is None:
            return

        rewrite = compute(team)
        update_fields = []
        if rewrite.linked_flag is not None:
            team.session_recording_linked_flag = rewrite.linked_flag
            update_fields.append("session_recording_linked_flag")
        if rewrite.trigger_groups is not None:
            team.session_recording_trigger_groups = rewrite.trigger_groups
            update_fields.append("session_recording_trigger_groups")
        if not update_fields:
            # A no-op save would still spend a write, a Celery task, and a RemoteConfig rebuild.
            return

        # Saving the instance rather than issuing a queryset `update()` is what fires the
        # `post_save` receiver that refreshes the team's RemoteConfig; a bulk update would leave
        # the cached SDK payload holding the old key. Both columns go in one save because that
        # refresh is queued per save, not per changed field.
        team.save(update_fields=update_fields)


def relink_teams(feature_flag: FeatureFlag, *, old_key: str) -> None:
    """Point every team gating replay on this flag at its current key.

    Teams are found by `old_key` rather than the flag's current one, because a trigger group is
    matched by the key it still holds — the one the flag has just stopped having.
    """
    new_key = feature_flag.key

    def rewrite(team: Team) -> ReplayGateRewrite:
        # Group indices come from the locked row, so a group added or reordered since this team was
        # selected still moves the reference the rename is about.
        trigger_groups = team.session_recording_trigger_groups
        moving = {ref.group_index: new_key for ref in trigger_group_flag_refs(trigger_groups) if ref.key == old_key}
        return ReplayGateRewrite(
            linked_flag=rewritten_linked_flag(
                team.session_recording_linked_flag, flag_id=feature_flag.pk, new_key=new_key
            ),
            trigger_groups=rewritten_trigger_groups(trigger_groups, moving),
        )

    # Ids only: `Team` is a wide model with several large JSONFields, and the columns this rewrites
    # are re-read under the lock anyway.
    for team_id in teams_gating_replay_on_flag(feature_flag, key=old_key).values_list("pk", flat=True):
        try:
            save_replay_gate_rewrites(team_id, rewrite)
        except Exception:
            # This runs after the rename has committed, so raising would fail a request that
            # already succeeded, and the retry would find the key unchanged and skip the relink
            # entirely. Report instead, per team, so one unwritable row doesn't strand the others.
            # `repair_replay_linked_flag_keys` picks the linked flag column back up later; it does
            # not read trigger groups, so a group left here stays stale until the next rename.
            logger.exception("replay_relink_failed", flag_id=feature_flag.pk, team_id=team_id)
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
    # Django admin, a shell, or a Celery task keep the gate intact too, and rather than to
    # model_activity_signal because activity logging is tunable in ways recording must not
    # inherit: `mute_selected_signals()` and the activity-log `signal_exclusions` can both
    # silently drop that signal, and a skipped relink turns replay off for every gating team.
    if raw or created:
        return
    before = snapshot_if_changed(instance, attr=_KEY_BEFORE_SAVE_ATTR)
    if before is None:
        return
    old_key = before["key"]

    # No `instance.deleted` guard, unlike `repair_replay_linked_flag_keys`, so the tombstone rename
    # `_free_key_held_by_soft_deleted_flags` does when freeing a soft-deleted flag's key relinks
    # too. Skipping it would leave the team on the now-freed original key, which a new flag could
    # claim next, silently gating replay on a flag the team never linked. Matching on the old key
    # does mean a flag that claims the freed key before this callback runs collects the trigger
    # groups instead; the alternative leaves them pointing at a key nothing resolves. The linked
    # flag column matches on id and is immune either way.

    # Deferred to commit because the serializer renames inside a transaction that holds
    # `select_for_update` on the flag row, and taking team locks in that window invites deadlocks.
    # Outside a transaction (admin, shell) `on_commit` runs the callback immediately.
    transaction.on_commit(lambda: relink_teams(instance, old_key=old_key))
