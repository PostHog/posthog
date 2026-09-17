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

from collections import defaultdict
from collections.abc import Callable, Collection, Mapping
from typing import Any

from django.db import transaction
from django.db.models import Q, QuerySet
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

import structlog

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.models import Team

from products.feature_flags.backend.field_snapshots import capture_fields_before_save, snapshot_if_changed
from products.feature_flags.backend.models.feature_flag import FeatureFlag

logger = structlog.get_logger(__name__)

REPLAY_GATE_DELETE_ERROR = (
    "This feature flag is used in session replay settings. Please remove it from replay settings before deleting."
)

LINKED_FLAG_COLUMN = "session_recording_linked_flag"
TRIGGER_GROUPS_COLUMN = "session_recording_trigger_groups"
REPLAY_GATE_COLUMNS = (LINKED_FLAG_COLUMN, TRIGGER_GROUPS_COLUMN)


@frozen
class TriggerGroupFlagRef:
    """One trigger group's reference to a feature flag, and where in the stored config it sits."""

    group_index: int
    stored_flag: Any
    key: str | None
    flag_id: int | None


@frozen
class ReplayGateRewrite:
    """New values for a team's gate columns. `None` leaves that column alone.

    A column that gates on nothing holds `None`, so `None` cannot also mean "leave this column
    alone". The two `clear_` flags therefore carry "store `None` here" on their own, and a flag
    set for a column wins over a value given for the same column.
    """

    linked_flag: dict[str, Any] | None = None
    trigger_groups: dict[str, Any] | None = None
    clear_linked_flag: bool = False
    clear_trigger_groups: bool = False


@frozen
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
    # `bool` subclasses `int`, so `{"id": true}` would otherwise read as a link to flag 1.
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
    return teams_gating_replay(project_id=feature_flag.team.project_id, flag_id=feature_flag.id, key=key)


def teams_gating_replay(*, project_id: int, flag_id: int, key: str) -> QuerySet[Team]:
    """`teams_gating_replay_on_flag` by id, for a caller that has no flag row to read.

    A `post_delete` receiver is one: the row is gone, and Django clears the id off the instance
    once the collector finishes.
    """
    return Team.objects.filter(
        Q(session_recording_linked_flag__contains={"id": flag_id})
        | Q(session_recording_trigger_groups__contains=_trigger_group_flag_probe(key))
        | Q(session_recording_trigger_groups__contains=_trigger_group_flag_probe({"key": key}))
        # An object reference holding a key the flag no longer has still names it by id. Matching
        # that too is what stops a delete stranding a reference the repair command could have
        # fixed, since deleting the flag takes away the only record of what the key meant.
        | Q(session_recording_trigger_groups__contains=_trigger_group_flag_probe({"id": flag_id})),
        project_id=project_id,
    )


def replay_gated_flags(project_id: int) -> ReplayFlagGates:
    """Single-project form of `replay_gated_flags_for_projects`."""
    return replay_gated_flags_for_projects([project_id]).get(
        project_id, ReplayFlagGates(flag_ids=frozenset(), flag_keys=frozenset())
    )


def replay_gated_flags_for_projects(project_ids: Collection[int]) -> Mapping[int, ReplayFlagGates]:
    """Every flag a team in each project gates session recording on, from both columns.

    One query for every project named, for callers checking many flags at once;
    `teams_gating_replay_on_flag` is the per-flag equivalent. Keyed by project because a flag key
    identifies one flag only within its own project, so pooling the keys would let a key stored
    in one project match a same-keyed flag in another. A project that gates on nothing is absent
    from the result rather than present and empty.
    """
    stored = Team.objects.filter(
        Q(session_recording_linked_flag__isnull=False) | Q(session_recording_trigger_groups__isnull=False),
        project_id__in=project_ids,
    ).values_list("project_id", "session_recording_linked_flag", "session_recording_trigger_groups")

    flag_ids: dict[int, set[int]] = defaultdict(set)
    flag_keys: dict[int, set[str]] = defaultdict(set)
    for project_id, linked_flag, trigger_groups in stored:
        if (flag_id := stored_flag_id(linked_flag)) is not None:
            flag_ids[project_id].add(flag_id)
        for ref in trigger_group_flag_refs(trigger_groups):
            if ref.key is not None:
                flag_keys[project_id].add(ref.key)
            if ref.flag_id is not None:
                flag_ids[project_id].add(ref.flag_id)
    return {
        project_id: ReplayFlagGates(
            flag_ids=frozenset(flag_ids[project_id]), flag_keys=frozenset(flag_keys[project_id])
        )
        for project_id in flag_ids.keys() | flag_keys.keys()
    }


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


@frozen
class _GateFlagRef:
    """One flag reference a pending write to the gate columns carries."""

    column: str
    flag_id: int | None
    key: str | None
    group_index: int | None = None


@frozen
class _ProjectFlags:
    """The live flags of one project that a set of references names."""

    keys_by_id: Mapping[int, str]
    keys: frozenset[str]

    def resolves(self, ref: _GateFlagRef) -> bool:
        """Whether this project holds the flag the reference names.

        A reference that carries an id is judged on the id alone. The id is what the flag-delete
        guard and `repair_replay_linked_flag_keys` match on, so an id no flag holds is unusable
        however good the key beside it looks.
        """
        if ref.flag_id is not None:
            return ref.flag_id in self.keys_by_id
        return ref.key is not None and ref.key in self.keys


def _gate_flag_refs(columns: Mapping[str, Any]) -> list[_GateFlagRef]:
    """Every flag reference in the gate columns a caller is about to write.

    A column the caller leaves out contributes nothing, so a request that sends one column never
    has the other one judged.
    """
    refs = []
    linked_flag = columns.get(LINKED_FLAG_COLUMN)
    if isinstance(linked_flag, dict):
        key = linked_flag.get("key")
        refs.append(
            _GateFlagRef(
                column=LINKED_FLAG_COLUMN,
                flag_id=stored_flag_id(linked_flag),
                key=key if isinstance(key, str) else None,
            )
        )
    for group_ref in trigger_group_flag_refs(columns.get(TRIGGER_GROUPS_COLUMN)):
        refs.append(
            _GateFlagRef(
                column=TRIGGER_GROUPS_COLUMN,
                flag_id=group_ref.flag_id,
                key=group_ref.key,
                group_index=group_ref.group_index,
            )
        )
    return refs


def _project_flags(project_id: int, refs: Collection[_GateFlagRef]) -> _ProjectFlags:
    rows = list(
        FeatureFlag.objects.filter(
            # Sorted so the `IN` lists keep a stable order, for the same reason `ReplayFlagGates.as_q`
            # sorts them.
            Q(id__in=sorted({ref.flag_id for ref in refs if ref.flag_id is not None}))
            | Q(key__in=sorted({ref.key for ref in refs if ref.key is not None})),
            team__project_id=project_id,
        ).values_list("id", "key")
    )
    # `FeatureFlag.objects` excludes soft-deleted flags, so a tombstoned flag resolves to nothing
    # here even though its row is still there.
    return _ProjectFlags(keys_by_id=dict(rows), keys=frozenset(key for _, key in rows))


def _unusable_flag_error(ref: _GateFlagRef) -> str:
    named = str(ref.flag_id) if ref.flag_id is not None else f"'{ref.key}'"
    # One message for a flag that is missing, soft-deleted, or in another project. Naming which
    # of the three it is would tell the caller about flags outside this project.
    if ref.column == LINKED_FLAG_COLUMN:
        return (
            f"Feature flag {named} is not available in this project. "
            "Pick a flag from this project, or clear the linked flag."
        )
    return (
        f"Group {ref.group_index}: feature flag {named} is not available in this project. "
        "Pick a flag from this project, or remove the flag from this group."
    )


def unusable_gate_flag_errors(project_id: int, columns: Mapping[str, Any]) -> dict[str, list[str]]:
    """Validation errors for every flag a gate write names that the project cannot record on.

    Keyed by column, so a caller can raise them against the field the client sent. Only the
    columns passed in are read, so a value already stored is never judged by a request that does
    not send it. That matters for the rows written before the id was normalized to an integer:
    they hold a string id that no `__contains={"id": ...}` probe matches, and they stay readable
    and writable until someone sends the column again.
    """
    refs = _gate_flag_refs(columns)
    if not refs:
        return {}
    flags = _project_flags(project_id, refs)
    errors: dict[str, list[str]] = defaultdict(list)
    for ref in refs:
        if not flags.resolves(ref):
            errors[ref.column].append(_unusable_flag_error(ref))
    return dict(errors)


def _canonical_gate_columns(project_id: int, columns: Mapping[str, Any]) -> dict[str, Any]:
    """The gate columns to store, with every reference that carries a flag id moved onto that
    flag's current key.

    A rename that commits while a settings edit is in flight leaves the client's payload naming
    the key the flag held when the settings page loaded. Storing that key would gate recording on
    a key no flag holds, which both SDKs read as "do not record". The stored id says which flag
    the client meant, so the key comes from the flag row instead.

    A reference that carries no id has nothing to resolve and keeps the key the client sent. That
    is the shape the replay settings UI writes for a trigger group, so a rename racing a trigger
    group edit can still store the pre-rename key. `repair_replay_linked_flag_keys` does not read
    trigger groups, so such a group stays stale.
    """
    identified = [ref for ref in _gate_flag_refs(columns) if ref.flag_id is not None]
    if not identified:
        return dict(columns)

    keys_by_id = _project_flags(project_id, identified).keys_by_id
    canonical = dict(columns)

    linked_flag = canonical.get(LINKED_FLAG_COLUMN)
    if isinstance(linked_flag, dict):
        flag_id = stored_flag_id(linked_flag)
        current_key = keys_by_id.get(flag_id) if flag_id is not None else None
        if flag_id is not None and current_key is not None:
            rewritten = rewritten_linked_flag(linked_flag, flag_id=flag_id, new_key=current_key)
            if rewritten is not None:
                canonical[LINKED_FLAG_COLUMN] = rewritten

    moving = {
        ref.group_index: keys_by_id[ref.flag_id]
        for ref in identified
        if ref.column == TRIGGER_GROUPS_COLUMN
        and ref.group_index is not None
        and ref.flag_id is not None
        and ref.flag_id in keys_by_id
    }
    if moving:
        rewritten_groups = rewritten_trigger_groups(canonical.get(TRIGGER_GROUPS_COLUMN), moving)
        if rewritten_groups is not None:
            canonical[TRIGGER_GROUPS_COLUMN] = rewritten_groups

    return canonical


def lock_team_for_replay_gate_write(team: Team, columns: Mapping[str, Any]) -> dict[str, Any]:
    """Take the team's gate lock, then return the columns to store, resolved under it.

    Call this inside the transaction that saves the columns. `save_replay_gate_rewrites` takes
    the same lock, so a relink and an API write of these columns run in one order or the other,
    and whichever runs second reads the flag key at that point.

    A flag hard-deleted between validation and this lock leaves nothing to resolve, so the
    client's value is stored as it came. That is the state a hard delete already leaves behind,
    and `repair_replay_linked_flag_keys` reports it as flag_missing on its next run.
    """
    # `no_key=True` for the reason `save_replay_gate_rewrites` gives: this write touches no key
    # column, so the lock must not block the `KEY SHARE` a foreign key check on this Team row
    # takes. Only the id is selected because the caller already holds the row it is saving.
    Team.objects.select_for_update(no_key=True).filter(pk=team.pk).values_list("pk", flat=True).first()
    return _canonical_gate_columns(team.project_id, columns)


def save_replay_gate_rewrites(team_id: int, compute: Callable[[Team], ReplayGateRewrite]) -> None:
    """Rewrite a team's gate columns under a row lock, in a single save.

    `compute` is handed the team as it exists inside the lock rather than a copy the caller read
    earlier. Callers load their teams in one batch and then loop, so an admin edit to this team's
    replay settings can land before its turn comes up. Both rewrites replace a whole column, so
    computing one from a stale copy would put the pre-edit column back and publish it to the SDKs.

    Taking the lock here is safe because this is the only row the function locks and the
    transaction commits before returning, so two calls for different teams cannot deadlock against
    each other. `relink_teams_on_key_change` defers to `on_commit` so the serializer's lock on the
    flag row is already released by the time this runs.
    """
    with transaction.atomic():
        # Loads every column rather than deferring: the `post_save` cache receiver reads about
        # thirty other fields, each its own query when deferred.
        # `no_key=True` because this writes no key column, so the lock does not block the
        # `KEY SHARE` that a foreign key check on this Team row takes. Two `FOR NO KEY UPDATE`
        # locks still conflict, so two calls to this function for one team stay serialized.
        # The Team API takes the same lock through `lock_team_for_replay_gate_write` before it
        # saves either column, so a settings edit and a rename run in one order or the other.
        # Whichever runs second reads the flag's key at that point, so both converge on it.
        team = Team.objects.select_for_update(no_key=True).filter(pk=team_id).first()
        if team is None:
            return

        rewrite = compute(team)
        update_fields = []
        if rewrite.clear_linked_flag or rewrite.linked_flag is not None:
            team.session_recording_linked_flag = None if rewrite.clear_linked_flag else rewrite.linked_flag
            update_fields.append(LINKED_FLAG_COLUMN)
        if rewrite.clear_trigger_groups or rewrite.trigger_groups is not None:
            team.session_recording_trigger_groups = None if rewrite.clear_trigger_groups else rewrite.trigger_groups
            update_fields.append(TRIGGER_GROUPS_COLUMN)
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
    matched by the key it still holds, which is the one the flag has just stopped having.
    """
    try:
        # Read into a list here rather than iterated straight in the loop below, because a queryset
        # runs its query on the first step of the loop, where the per-team handler cannot catch it.
        team_ids = list(teams_gating_replay_on_flag(feature_flag, key=old_key).values_list("pk", flat=True))
    except Exception:
        # This read runs after the rename has committed, so a fault here, such as a connection a
        # failover dropped, must not raise for the same reason a write failure below must not: it
        # would fail a request that already succeeded. `repair_replay_linked_flag_keys` picks the
        # linked flag column back up later.
        logger.exception("replay_relink_lookup_failed", flag_id=feature_flag.pk)
        capture_exception()
        return

    def rewrite(team: Team) -> ReplayGateRewrite:
        # Read once per team, under that team's row lock, rather than once before the loop. Two
        # renames of the same flag committed close together fire their `on_commit` callbacks with
        # no ordering guarantee between them, and a rename can also land partway through this
        # loop. Every relink holding this team's row lock reads the key at this point, so they
        # converge on the stored key instead of leaving later teams on the key this callback
        # started with. A Team API write takes no such lock and is not ordered against them.
        # `objects_including_soft_deleted` also finds the tombstone that
        # `_free_key_held_by_soft_deleted_flags` renames.
        new_key = (
            FeatureFlag.objects_including_soft_deleted.filter(pk=feature_flag.pk).values_list("key", flat=True).first()
        )
        if new_key is None:
            # The row is gone entirely, not just soft-deleted, so there is no key to point this
            # team at. `repair_replay_linked_flag_keys` reports it as flag_missing on its next run.
            return ReplayGateRewrite()
        trigger_groups = team.session_recording_trigger_groups
        # Matched by id as well as by key, because `teams_gating_replay_on_flag` also selects a
        # team whose group names this flag by id while holding a key the flag no longer has. The
        # rename is the last moment that stored id still resolves to a key.
        # `repair_replay_linked_flag_keys` does not read trigger groups, so a group skipped here
        # keeps the stale key for good. A bare string reference carries no id, so it still moves
        # on its key alone.
        moving = {
            ref.group_index: new_key
            for ref in trigger_group_flag_refs(trigger_groups)
            if ref.key == old_key or ref.flag_id == feature_flag.pk
        }
        return ReplayGateRewrite(
            linked_flag=rewritten_linked_flag(
                team.session_recording_linked_flag, flag_id=feature_flag.pk, new_key=new_key
            ),
            trigger_groups=rewritten_trigger_groups(trigger_groups, moving),
        )

    for team_id in team_ids:
        try:
            save_replay_gate_rewrites(team_id, rewrite)
        except Exception:
            # This runs after the rename has committed, so raising would fail a request that
            # already succeeded. `repair_replay_linked_flag_keys` picks the linked flag column back
            # up later. It does not read trigger groups, so a group left here stays stale.
            logger.exception("replay_relink_failed", flag_id=feature_flag.pk, team_id=team_id)
            capture_exception()


def clear_replay_gates(*, flag_id: int, key: str, team_id: int) -> None:
    """Drop every reference to a hard-deleted flag from the teams that gate replay on it.

    A hard delete leaves the reference naming a flag that no longer exists, and no key to move it
    onto, so the only repair left is to take the reference out. `repair_replay_linked_flag_keys`
    can only report such a row, as flag_missing.
    """

    def clear(team: Team) -> ReplayGateRewrite:
        clear_linked_flag = stored_flag_id(team.session_recording_linked_flag) == flag_id
        dropped = {
            ref.group_index
            for ref in trigger_group_flag_refs(team.session_recording_trigger_groups)
            # A reference carrying an id is judged on that id alone, the way `_ProjectFlags.resolves`
            # and `rewritten_linked_flag` judge one, and the way the linked flag column is judged
            # just above. A group holding a live flag's id beside the deleted flag's key names the
            # live flag, and dropping it would take a working recording rule with it.
            if (ref.flag_id == flag_id if ref.flag_id is not None else ref.key == key)
        }
        if not dropped:
            return ReplayGateRewrite(clear_linked_flag=clear_linked_flag)

        # The whole group goes, not only its `conditions.flag`. A group that kept its other
        # conditions after losing its flag would start matching the sessions the flag held back,
        # so removing the reference would widen recording rather than end it.
        kept = [
            group for index, group in enumerate(team.session_recording_trigger_groups["groups"]) if index not in dropped
        ]
        return ReplayGateRewrite(
            clear_linked_flag=clear_linked_flag,
            trigger_groups={**team.session_recording_trigger_groups, "groups": kept} if kept else None,
            clear_trigger_groups=not kept,
        )

    try:
        project_id = Team.objects.filter(pk=team_id).values_list("project_id", flat=True).first()
        if project_id is None:
            # The flag's own team is gone too, so this is a team or project delete cascading. Every
            # team that could hold a reference is going with it.
            return
        team_ids = list(
            teams_gating_replay(project_id=project_id, flag_id=flag_id, key=key).values_list("pk", flat=True)
        )
    except Exception:
        # These reads run after the delete has committed, so a fault here must not raise for the
        # same reason a write failure below must not: it would fail a request that already
        # succeeded.
        logger.exception("replay_gate_clear_lookup_failed", flag_id=flag_id)
        capture_exception()
        return

    for gating_team_id in team_ids:
        try:
            save_replay_gate_rewrites(gating_team_id, clear)
        except Exception:
            logger.exception("replay_gate_clear_failed", flag_id=flag_id, team_id=gating_team_id)
            capture_exception()


@receiver(post_delete, sender=FeatureFlag)
def clear_replay_gates_on_delete(sender: type[FeatureFlag], instance: FeatureFlag, **kwargs: Any) -> None:
    # The API serializer refuses to delete a flag a team gates replay on, so this covers the
    # writers that go around it: a management command, a cascade, and the Django admin. Wired to
    # the model signal for the reason `relink_teams_on_key_change` is.
    #
    # The id, key and team are read here rather than in the callback because Django clears the id
    # off the instance once the collector finishes, which is before the callback runs.
    flag_id = instance.pk
    key = instance.key
    team_id = instance.team_id
    transaction.on_commit(lambda: clear_replay_gates(flag_id=flag_id, key=key, team_id=team_id))


_KEY_BEFORE_SAVE_ATTR = "_replay_link_key_before_save"


@receiver(pre_save, sender=FeatureFlag)
def capture_replay_link_key_before_save(
    sender: type[FeatureFlag],
    instance: FeatureFlag,
    raw: bool = False,
    update_fields: frozenset[str] | None = None,
    **kwargs: Any,
) -> None:
    # `objects_including_soft_deleted` so the tombstone rename that
    # `_free_key_held_by_soft_deleted_flags` does is captured too.
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
    # claim next, silently gating replay on a flag the team never linked.

    # Deferred to commit because the serializer renames inside a transaction that holds
    # `select_for_update` on the flag row, and taking team locks in that window invites deadlocks.
    # Outside a transaction (admin, shell) `on_commit` runs the callback immediately.
    transaction.on_commit(lambda: relink_teams(instance, old_key=old_key))
