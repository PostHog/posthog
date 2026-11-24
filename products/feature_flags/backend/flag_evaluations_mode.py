"""Writes of OrganizationFeatureFlagsConfig.flag_evaluations_mode for a list of organizations."""

from collections.abc import Collection, Iterable, Mapping, Sequence
from datetime import datetime
from enum import StrEnum
from itertools import batched
from uuid import UUID

from django.db import connection
from django.db.models import Count

from posthog.dataclasses import frozen
from posthog.models import Organization, Team

from products.experiments.backend.facade import count_running_experiments_needing_flag_calls_in_events
from products.feature_flags.backend.facade.enums import FlagEvaluationsMode
from products.feature_flags.backend.facade.flags import NO_ROW_CONFIG, FlagEvaluationsConfig
from products.feature_flags.backend.models.organization_feature_flags_config import OrganizationFeatureFlagsConfig

ID_LOOKUP_BATCH_SIZE = 10_000

FLAG_EVALUATIONS_MODES_HELP = (
    "0 reads events. 1 reads flag_evaluations for the flag Usage tab, the per-project counts on a flag's Projects "
    "tab, events lists filtered to only $feature_flag_called, such as the Activity page, and the flag call and "
    "experiment enrollment counts on the home page. On 1, a HogQL query, such as an insight, also reads "
    "flag_evaluations when it pins $feature_flag_called and $feature_flag to string keys, and its date range starts "
    "within the table's coverage. Other queries, including default experiment exposures, read events. 1 also hides "
    "$feature_flag_called from event pickers, and refuses a new action step on it and a new cohort criterion on it "
    "that the batch calculation would read from events. 2 also stops ingestion writing $feature_flag_called to "
    "events for the teams it copies to flag_evaluations, which on PostHog Cloud is every team outside "
    "INGESTION_FLAG_EVALUATIONS_EXCLUDED_TEAMS, unless the organization keeps writing flag calls to events. With "
    "that kept, every reader behaves as described here, and FLAG_EVALUATIONS_READS_FORCE_EVENTS moves the "
    "organization back to events. The events copy starts when that takes effect and holds no earlier calls, so a "
    "read that moves back to events misses the calls only flag_evaluations holds. On 2, a HogQL query reads flag_evaluations for any date range and "
    "fails when it can't, a query that mixes flag calls with other events reads both tables, realtime cohorts refuse new flag-call criteria, and flags keep no last called time unless "
    "it syncs from flag_evaluations. On PostHog Cloud the table is available in SQL on every mode. Self-hosted, it "
    "is available on 1 and 2."
)


@frozen
class OrganizationModeChange:
    organization_id: UUID
    organization_name: str
    organization_created_at: datetime
    # Teams of the organization, for display only. The write never touches team rows.
    team_count: int
    # Running experiments that read $feature_flag_called from events without its $experiment_exposure copy.
    # FLAG_EVALUATIONS_ONLY stops those events writes unless they are kept, and events lacks the calls from before the
    # writes stopped or were kept.
    running_experiments_needing_flag_calls_in_events: int
    current_mode: int
    target_mode: int
    # Whether ingestion kept writing flag calls to events before the write, and after it. Only mode 2 keeps them.
    current_keeps_events_writes: bool
    target_keeps_events_writes: bool
    # True when the write moved the organization to target_mode, or would on a dry run.
    changed: bool
    # True when the organization is above target_mode and allow_downgrade is off.
    left_above_mode: bool


@frozen
class RecordedChange:
    """One line of a --write-changed-ids file: an organization's settings before and after one run changed them."""

    organization_id: UUID
    before: FlagEvaluationsConfig
    after: FlagEvaluationsConfig

    def to_line(self) -> str:
        return (
            f"{self.organization_id} {self.before.mode} {int(self.before.keeps_events_writes)} "
            f"{self.after.mode} {int(self.after.keeps_events_writes)}"
        )

    @classmethod
    def from_line(cls, text: str) -> "RecordedChange":
        """Parse `<organization id> <mode before> <kept before> <mode after> <kept after>`, where a kept value is 0 or
        1. Raises ValueError on any other text."""
        columns = text.split()
        if len(columns) != 5 or any(kept not in ("0", "1") for kept in (columns[2], columns[4])):
            raise ValueError(f"{text!r} is not `<organization id> <mode before> <0|1> <mode after> <0|1>`")
        return cls(
            organization_id=UUID(columns[0]),
            before=FlagEvaluationsConfig(
                mode=FlagEvaluationsMode(int(columns[1])), keeps_events_writes=columns[2] == "1"
            ),
            after=FlagEvaluationsConfig(
                mode=FlagEvaluationsMode(int(columns[3])), keeps_events_writes=columns[4] == "1"
            ),
        )

    @classmethod
    def from_mode_change(cls, change: OrganizationModeChange) -> "RecordedChange":
        return cls(
            organization_id=change.organization_id,
            before=FlagEvaluationsConfig(
                mode=change.current_mode, keeps_events_writes=change.current_keeps_events_writes
            ),
            after=FlagEvaluationsConfig(mode=change.target_mode, keeps_events_writes=change.target_keeps_events_writes),
        )


def is_recorded_change(text: str) -> bool:
    try:
        RecordedChange.from_line(text)
    except ValueError:
        return False
    return True


_LINE_TEMPLATE = f"{'h' * 8}-{'h' * 4}-{'h' * 4}-{'h' * 4}-{'h' * 12} m k m k"
_TEMPLATE_CHARACTERS = {
    "h": "0123456789abcdef",
    "m": "".join(str(mode) for mode in FlagEvaluationsMode.values),
    "k": "01",
}


def _is_unfinished_record(text: str) -> bool:
    """Whether the text is a part of a line that RecordedChange.to_line writes, cut short after something other than
    the id. A bare id is excluded, because older runs wrote bare ids as whole lines."""
    return (
        0 < len(text) < len(_LINE_TEMPLATE)
        and len(text) != _LINE_TEMPLATE.index(" ")
        and all(character in _TEMPLATE_CHARACTERS.get(slot, slot) for character, slot in zip(text, _LINE_TEMPLATE))
    )


def parse_recorded_changes(content: str) -> tuple[list[RecordedChange], str]:
    """The records in the text of a --write-changed-ids file, and its unfinished last line, or "" when it has none.

    An unfinished last line has no final newline and is the start of a record cut short. A run syncs a chunk's lines
    to disk before the chunk commits, so such a line comes from a chunk that never committed. Any other line that is
    not a record raises ValueError, whose message starts with the line number. A caller may truncate the unfinished
    line, so anything that a run could not have written refuses instead.
    """
    body, unfinished = content, ""
    if content and not content.endswith("\n"):
        start = content.rfind("\n") + 1
        if _is_unfinished_record(content[start:]):
            body, unfinished = content[:start], content[start:]
    changes = []
    for line_number, line in enumerate(body.splitlines(), start=1):
        if not (text := line.strip()):
            continue
        try:
            changes.append(RecordedChange.from_line(text))
        except ValueError as error:
            raise ValueError(f"{line_number}: {error}") from error
    return changes, unfinished


@frozen
class RecordedHistory:
    """What the runs that wrote a changed-ids file did to one organization."""

    # The settings before the first run that changed the organization.
    before: FlagEvaluationsConfig
    # Every setting that a record of the organization started or ended at. A run writes its records before its chunk
    # commits, so the organization can hold any of them, not only the last record's "after".
    reached: frozenset[FlagEvaluationsConfig]
    # False when a record starts from settings that no earlier record of the organization started or ended at.
    # Something outside the runs then changed the organization between two of them.
    unbroken: bool


def collapse_recorded_changes(changes: Iterable[RecordedChange]) -> dict[UUID, RecordedHistory]:
    """The history of each organization, in the order the records first name them. Records are in the order the runs
    appended them.

    A record may start from any settings the organization's earlier records reached, not only from the last one. A
    chunk writes its lines before it commits, so a chunk that never committed leaves records that the rerun repeats.
    A restore between two runs on the same file also returns the organization to settings an earlier record holds.
    """
    befores: dict[UUID, FlagEvaluationsConfig] = {}
    reached: dict[UUID, set[FlagEvaluationsConfig]] = {}
    unbroken: dict[UUID, bool] = {}
    for change in changes:
        organization_id = change.organization_id
        befores.setdefault(organization_id, change.before)
        seen = reached.setdefault(organization_id, {change.before})
        unbroken[organization_id] = unbroken.get(organization_id, True) and change.before in seen
        seen.add(change.after)
    return {
        organization_id: RecordedHistory(
            before=before, reached=frozenset(reached[organization_id]), unbroken=unbroken[organization_id]
        )
        for organization_id, before in befores.items()
    }


class RestoreOutcome(StrEnum):
    RESTORED = "restored"
    # The organization already has its settings from before the runs, such as after a restore that ran before.
    ALREADY_RESTORED = "already restored"
    # Something outside the recorded runs changed the organization. The restore keeps its settings.
    CHANGED_OUTSIDE_THE_RUNS = "changed outside the recorded runs, kept"


@frozen
class OrganizationRestore:
    organization_id: UUID
    current: FlagEvaluationsConfig
    target: FlagEvaluationsConfig
    outcome: RestoreOutcome
    # The same count as on OrganizationModeChange, or None when the restore did not count it. The restore counts it only
    # for an organization that it moves to FLAG_EVALUATIONS_ONLY. A run warns about experiments only on that mode too.
    running_experiments_needing_flag_calls_in_events: int | None


class UnknownIdsError(Exception):
    def __init__(self, label: str, missing_ids: Collection[object]) -> None:
        super().__init__(f"Unknown {label} id(s): {', '.join(sorted(map(str, missing_ids)))}")


def select_organization_ids(*, created_after: datetime | None = None) -> list[UUID]:
    """Ids of every organization, or of those created after `created_after`, oldest first."""
    organizations = Organization.objects.all()
    if created_after is not None:
        organizations = organizations.filter(created_at__gt=created_after)
    return list(organizations.order_by("created_at", "id").values_list("id", flat=True))


def get_organizations(organization_ids: Collection[UUID]) -> list[Organization]:
    """The given organizations, oldest first.

    Raises UnknownIdsError when an id does not exist, so that a caller refuses the whole request
    and names the bad id instead of skipping it.
    """
    organizations = list(Organization.objects.filter(id__in=organization_ids).order_by("created_at", "id"))
    if missing_ids := set(organization_ids) - {organization.id for organization in organizations}:
        raise UnknownIdsError("organization", missing_ids)
    return organizations


def find_unknown_organization_ids(organization_ids: Collection[UUID]) -> set[UUID]:
    """The ids that match no organization. It loads only ids, in batches, so a list of hundreds of thousands of
    ids stays cheap."""
    missing_ids: set[UUID] = set()
    for batch in batched(organization_ids, ID_LOOKUP_BATCH_SIZE, strict=False):
        missing_ids |= set(batch) - set(Organization.objects.filter(id__in=batch).values_list("id", flat=True))
    return missing_ids


def get_organizations_of_teams(team_ids: Collection[int]) -> list[Organization]:
    """The organizations that own the given teams, oldest first. Raises UnknownIdsError like get_organizations."""
    organization_id_by_team_id = dict(Team.objects.filter(id__in=team_ids).values_list("id", "organization_id"))
    if missing_ids := set(team_ids) - organization_id_by_team_id.keys():
        raise UnknownIdsError("team", missing_ids)
    return get_organizations(set(organization_id_by_team_id.values()))


def _read_stored_configs(organization_ids: Collection[UUID], *, lock: bool) -> dict[UUID, FlagEvaluationsConfig]:
    """The config of each listed organization that has a config row.

    With `lock`, the read locks those rows in id order until the transaction ends. Every writer of these rows locks
    them in that order, so two writers cannot deadlock, and the rows keep the configs the read returned.
    """
    rows = OrganizationFeatureFlagsConfig.objects.filter(organization_id__in=organization_ids).order_by(
        "organization_id"
    )
    if lock:
        rows = rows.select_for_update()
    return {
        organization_id: FlagEvaluationsConfig(mode=mode, keeps_events_writes=keeps_events_writes)
        for organization_id, mode, keeps_events_writes in rows.values_list(
            "organization_id", "flag_evaluations_mode", "keep_writing_flag_calls_to_events"
        )
    }


def _restore_configs(histories: Mapping[UUID, RecordedHistory]) -> None:
    """Set each organization's row back to its history's `before`. The caller holds the rows' locks."""
    if not histories:
        return
    table = OrganizationFeatureFlagsConfig._meta.db_table
    query = f"""
        UPDATE {table}
           SET flag_evaluations_mode = restore.mode,
               keep_writing_flag_calls_to_events = restore.kept
          FROM unnest(%s::uuid[], %s::smallint[], %s::boolean[]) AS restore(organization_id, mode, kept)
         WHERE {table}.organization_id = restore.organization_id
    """
    rows = [
        (str(organization_id), int(history.before.mode), history.before.keeps_events_writes)
        for organization_id, history in sorted(histories.items())
    ]
    with connection.cursor() as cursor:
        cursor.execute(query, [list(column) for column in zip(*rows)])


def restore_organizations_flag_evaluations_configs(
    histories: Mapping[UUID, RecordedHistory], *, dry_run: bool, count_experiments: bool = True
) -> list[OrganizationRestore]:
    """Put each organization back to the settings it had before the recorded runs, in the order given.

    The restore writes an organization only while the organization has settings that one of its records reached, and
    each of its records starts from settings that an earlier record of it reached (`RecordedHistory.unbroken`). It
    keeps the settings of any other organization, which changed outside the runs. It leaves an organization that
    already has its settings from before the runs alone, so a restore that runs again changes nothing more.

    Opens no transaction. The caller wraps the call in one, because the row locks it takes last until the
    transaction ends.
    """
    # The UPDATE locks rows in the order its plan visits them. The read locks them first, in id order.
    stored_configs = _read_stored_configs(list(histories), lock=not dry_run)

    def outcome_of(organization_id: UUID) -> RestoreOutcome:
        history, stored = histories[organization_id], stored_configs.get(organization_id)
        if (stored or NO_ROW_CONFIG) == history.before:
            return RestoreOutcome.ALREADY_RESTORED
        # A run wrote a row for every organization it recorded. A missing row means something outside the runs
        # deleted it.
        if stored is not None and history.unbroken and stored in history.reached:
            return RestoreOutcome.RESTORED
        return RestoreOutcome.CHANGED_OUTSIDE_THE_RUNS

    outcomes = {organization_id: outcome_of(organization_id) for organization_id in histories}
    if not dry_run:
        _restore_configs(
            {
                organization_id: histories[organization_id]
                for organization_id, outcome in outcomes.items()
                if outcome == RestoreOutcome.RESTORED
            }
        )
    return [
        OrganizationRestore(
            organization_id=organization_id,
            current=stored_configs.get(organization_id, NO_ROW_CONFIG),
            target=history.before,
            outcome=outcomes[organization_id],
            running_experiments_needing_flag_calls_in_events=(
                count_running_experiments_needing_flag_calls_in_events(organization_id)
                if count_experiments
                and outcomes[organization_id] == RestoreOutcome.RESTORED
                and history.before.mode == FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY
                else None
            ),
        )
        for organization_id, history in histories.items()
    ]


def _upsert_modes(
    organization_ids: Collection[UUID],
    mode: FlagEvaluationsMode,
    *,
    keep_writing_flag_calls_to_events: bool,
    allow_downgrade: bool,
    ids_without_row: Collection[UUID] = (),
) -> set[UUID]:
    """Write the mode in one statement and return the ids of the rows it changed.

    The WHERE clause compares against the stored mode at write time. Without allow_downgrade, a
    concurrent write that raised an organization above `mode` after the caller read it is kept. A row already at
    `mode` changes only when its kept events writes differ.

    `ids_without_row` lists the organizations that had no row when the caller read their configs. The statement only
    inserts their rows, so it keeps a row that a concurrent writer inserted after the read.
    """
    if not organization_ids:
        return set()
    table = OrganizationFeatureFlagsConfig._meta.db_table
    comparison = "<>" if allow_downgrade else "<"
    query = f"""
        INSERT INTO {table} (organization_id, flag_evaluations_mode, keep_writing_flag_calls_to_events)
        SELECT unnest(%s::uuid[]), %s, %s
        ON CONFLICT (organization_id) DO UPDATE
           SET flag_evaluations_mode = EXCLUDED.flag_evaluations_mode,
               keep_writing_flag_calls_to_events = EXCLUDED.keep_writing_flag_calls_to_events
         WHERE ({table}.flag_evaluations_mode {comparison} EXCLUDED.flag_evaluations_mode
                OR ({table}.flag_evaluations_mode = EXCLUDED.flag_evaluations_mode
                    AND {table}.keep_writing_flag_calls_to_events <> EXCLUDED.keep_writing_flag_calls_to_events))
           AND {table}.organization_id <> ALL(%s::uuid[])
        RETURNING organization_id
    """
    # The statement locks existing rows in the order of the array, so every writer sorts the ids to lock
    # overlapping rows in the same order.
    with connection.cursor() as cursor:
        cursor.execute(
            query,
            [
                [str(organization_id) for organization_id in sorted(organization_ids)],
                int(mode),
                keep_writing_flag_calls_to_events,
                [str(organization_id) for organization_id in ids_without_row],
            ],
        )
        return {row[0] for row in cursor.fetchall()}


def set_organizations_flag_evaluations_mode(
    organizations: Sequence[Organization],
    mode: FlagEvaluationsMode,
    *,
    allow_downgrade: bool,
    dry_run: bool,
    count_experiments: bool = True,
    keep_writing_flag_calls_to_events: bool = False,
) -> list[OrganizationModeChange]:
    """Move the organizations to `mode`, in the order given.

    An organization above `mode` stays where it is unless `allow_downgrade` is set. Lowering an
    organization from FLAG_EVALUATIONS_ONLY restarts events writes and leaves a gap in the events
    table.

    The reads and the write take one statement each for the whole list. Only the experiments count
    runs once per organization. `count_experiments=False` skips it and reports 0.

    `keep_writing_flag_calls_to_events` applies only to FLAG_EVALUATIONS_ONLY. Ingestion then keeps writing
    $feature_flag_called to events, and the readers behave as on FLAG_EVALUATIONS_ONLY. Any other mode clears it.

    Opens no transaction. Unless `dry_run` is set, the caller wraps the call in one, because the call locks the
    organizations' rows until the transaction ends.
    """
    organization_ids = [organization.id for organization in organizations]
    if len(set(organization_ids)) != len(organization_ids):
        raise ValueError("Each organization must appear once")
    # The lock keeps each row at the config the read returns. A --write-changed-ids record of that config then
    # matches the config the write replaced. A row that does not exist yet has nothing to lock.
    stored_configs = _read_stored_configs(organization_ids, lock=not dry_run)
    current_configs = {
        organization_id: stored_configs.get(organization_id, NO_ROW_CONFIG) for organization_id in organization_ids
    }
    keeps_events_writes = keep_writing_flag_calls_to_events and mode == FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY
    team_counts = dict(
        Team.objects.filter(organization_id__in=organization_ids)
        .values("organization_id")
        .annotate(team_count=Count("id"))
        .values_list("organization_id", "team_count")
    )
    # Only the organizations that the read says move are written. A missing row reads EVENTS, so a
    # write of EVENTS to it would insert a row and report a change that no reader can see.
    moving_ids = {
        organization_id
        for organization_id, current in current_configs.items()
        if current.mode < mode
        or (allow_downgrade and current.mode > mode)
        or (current.mode == mode and current.keeps_events_writes != keeps_events_writes)
    }
    changed_ids = (
        moving_ids
        if dry_run
        else _upsert_modes(
            moving_ids,
            mode,
            keep_writing_flag_calls_to_events=keeps_events_writes,
            allow_downgrade=allow_downgrade,
            ids_without_row=moving_ids - stored_configs.keys(),
        )
    )
    return [
        OrganizationModeChange(
            organization_id=organization.id,
            organization_name=organization.name,
            organization_created_at=organization.created_at,
            team_count=team_counts.get(organization.id, 0),
            running_experiments_needing_flag_calls_in_events=(
                count_running_experiments_needing_flag_calls_in_events(organization.id) if count_experiments else 0
            ),
            current_mode=current_configs[organization.id].mode,
            target_mode=mode,
            current_keeps_events_writes=current_configs[organization.id].keeps_events_writes,
            target_keeps_events_writes=keeps_events_writes,
            changed=organization.id in changed_ids,
            left_above_mode=current_configs[organization.id].mode > mode and not allow_downgrade,
        )
        for organization in organizations
    ]
