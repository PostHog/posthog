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
from products.feature_flags.backend.facade.flags import FlagEvaluationsConfig, get_organization_flag_evaluations_configs
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


@frozen
class RecordedHistory:
    """What the runs that wrote a changed-ids file did to one organization."""

    # The settings before the first run that changed the organization.
    before: FlagEvaluationsConfig
    # The settings after the last run that changed it.
    after: FlagEvaluationsConfig
    # False when a record does not start from the settings the previous record ended at. Something outside the runs
    # then changed the organization between two of them.
    unbroken: bool


def collapse_recorded_changes(changes: Iterable[RecordedChange]) -> dict[UUID, RecordedHistory]:
    """The history of each organization, in the order the records first name them. Records are in the order the runs
    appended them."""
    histories: dict[UUID, RecordedHistory] = {}
    for change in changes:
        previous = histories.get(change.organization_id)
        histories[change.organization_id] = (
            RecordedHistory(before=change.before, after=change.after, unbroken=True)
            if previous is None
            else RecordedHistory(
                before=previous.before,
                after=change.after,
                unbroken=previous.unbroken and previous.after == change.before,
            )
        )
    return histories


class RestoreOutcome(StrEnum):
    RESTORED = "restored"
    # The organization already has its settings from before the runs, such as after a restore that ran before.
    ALREADY_RESTORED = "already restored"
    # Something outside the recorded runs changed the organization, so the restore keeps its settings.
    CHANGED_OUTSIDE_THE_RUNS = "changed outside the recorded runs, kept"


@frozen
class OrganizationRestore:
    organization_id: UUID
    current: FlagEvaluationsConfig
    target: FlagEvaluationsConfig
    outcome: RestoreOutcome
    # As on OrganizationModeChange. Counted only for a restored organization, and 0 when counting is off.
    running_experiments_needing_flag_calls_in_events: int


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


def _lock_organization_configs(organization_ids: Collection[UUID]) -> None:
    """Lock the organizations' config rows in id order, the order every writer of these rows locks them in."""
    list(
        OrganizationFeatureFlagsConfig.objects.select_for_update()
        .filter(organization_id__in=organization_ids)
        .order_by("organization_id")
        .values_list("organization_id", flat=True)
    )


def _restore_configs(histories: Mapping[UUID, RecordedHistory]) -> set[UUID]:
    """Set each organization's row back to its history's `before`, only where the row still holds its history's
    `after`. Returns the ids of the rows it changed. It writes no row that is missing."""
    if not histories:
        return set()
    table = OrganizationFeatureFlagsConfig._meta.db_table
    query = f"""
        UPDATE {table}
           SET flag_evaluations_mode = restore.mode,
               keep_writing_flag_calls_to_events = restore.kept
          FROM unnest(%s::uuid[], %s::smallint[], %s::boolean[], %s::smallint[], %s::boolean[])
               AS restore(organization_id, mode, kept, expected_mode, expected_kept)
         WHERE {table}.organization_id = restore.organization_id
           AND {table}.flag_evaluations_mode = restore.expected_mode
           AND {table}.keep_writing_flag_calls_to_events = restore.expected_kept
        RETURNING {table}.organization_id
    """
    organization_ids = sorted(histories)
    with connection.cursor() as cursor:
        cursor.execute(
            query,
            [
                [str(organization_id) for organization_id in organization_ids],
                [int(histories[organization_id].before.mode) for organization_id in organization_ids],
                [histories[organization_id].before.keeps_events_writes for organization_id in organization_ids],
                [int(histories[organization_id].after.mode) for organization_id in organization_ids],
                [histories[organization_id].after.keeps_events_writes for organization_id in organization_ids],
            ],
        )
        return {row[0] for row in cursor.fetchall()}


def restore_organizations_flag_evaluations_configs(
    histories: Mapping[UUID, RecordedHistory], *, dry_run: bool, count_experiments: bool = True
) -> list[OrganizationRestore]:
    """Put each organization back to the settings it had before the recorded runs, in the order given.

    An organization is restored only while it still has the settings the last run left it with, and its records
    chain. Any other organization changed outside the runs, and the restore keeps its settings. An organization that
    already has its settings from before the runs is left alone, so a restore that runs again changes nothing more.

    Opens no transaction. The caller wraps the call in one, because the row locks it takes last until the
    transaction ends.
    """
    organization_ids = list(histories)
    if not dry_run:
        # The UPDATE locks rows in the order its plan visits them. Locking them in id order first keeps the restore
        # from deadlocking with another writer, and holds the rows still between the read and the write.
        _lock_organization_configs(organization_ids)
    current_configs = get_organization_flag_evaluations_configs(organization_ids)

    def outcome_from_read(organization_id: UUID) -> RestoreOutcome:
        history, current = histories[organization_id], current_configs[organization_id]
        if current == history.before:
            return RestoreOutcome.ALREADY_RESTORED
        if history.unbroken and current == history.after:
            return RestoreOutcome.RESTORED
        return RestoreOutcome.CHANGED_OUTSIDE_THE_RUNS

    outcomes = {organization_id: outcome_from_read(organization_id) for organization_id in organization_ids}
    restorable = {
        organization_id: histories[organization_id]
        for organization_id, outcome in outcomes.items()
        if outcome == RestoreOutcome.RESTORED
    }
    restored_ids = set(restorable) if dry_run else _restore_configs(restorable)
    results = []
    for organization_id in organization_ids:
        outcome = outcomes[organization_id]
        if outcome == RestoreOutcome.RESTORED and organization_id not in restored_ids:
            # The read saw a config that the row does not hold, which happens only when the organization has no row.
            outcome = RestoreOutcome.CHANGED_OUTSIDE_THE_RUNS
        results.append(
            OrganizationRestore(
                organization_id=organization_id,
                current=current_configs[organization_id],
                target=histories[organization_id].before,
                outcome=outcome,
                running_experiments_needing_flag_calls_in_events=(
                    count_running_experiments_needing_flag_calls_in_events(organization_id)
                    if count_experiments and outcome == RestoreOutcome.RESTORED
                    else 0
                ),
            )
        )
    return results


def _upsert_modes(
    organization_ids: Collection[UUID],
    mode: FlagEvaluationsMode,
    *,
    keep_writing_flag_calls_to_events: bool,
    allow_downgrade: bool,
) -> set[UUID]:
    """Write the mode in one statement and return the ids of the rows it changed.

    The WHERE clause compares against the stored mode at write time. Without allow_downgrade, a
    concurrent write that raised an organization above `mode` after the caller read it is kept. A row already at
    `mode` changes only when its kept events writes differ.
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
         WHERE {table}.flag_evaluations_mode {comparison} EXCLUDED.flag_evaluations_mode
            OR ({table}.flag_evaluations_mode = EXCLUDED.flag_evaluations_mode
                AND {table}.keep_writing_flag_calls_to_events <> EXCLUDED.keep_writing_flag_calls_to_events)
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

    Opens no transaction. A caller that must apply the whole list or none of it wraps the call.
    """
    organization_ids = [organization.id for organization in organizations]
    if len(set(organization_ids)) != len(organization_ids):
        raise ValueError("Each organization must appear once")
    current_configs = get_organization_flag_evaluations_configs(organization_ids)
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
            moving_ids, mode, keep_writing_flag_calls_to_events=keeps_events_writes, allow_downgrade=allow_downgrade
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
