"""Writes of OrganizationFeatureFlagsConfig.flag_evaluations_mode for a list of organizations."""

from collections.abc import Collection, Sequence
from datetime import datetime
from itertools import batched
from uuid import UUID

from django.db import connection
from django.db.models import Count

from posthog.dataclasses import frozen
from posthog.models import Organization, Team

from products.experiments.backend.facade import count_running_experiments_needing_flag_calls_in_events
from products.feature_flags.backend.facade.enums import FlagEvaluationsMode
from products.feature_flags.backend.facade.flags import get_organization_flag_evaluations_modes
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
    "INGESTION_FLAG_EVALUATIONS_EXCLUDED_TEAMS. On 2, a HogQL query reads flag_evaluations for any date range and "
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
    # FLAG_EVALUATIONS_ONLY stops those events writes, so those reads find no new calls.
    running_experiments_needing_flag_calls_in_events: int
    current_mode: int
    target_mode: int
    # True when the write moved the organization to target_mode, or would on a dry run.
    changed: bool
    # True when the organization is above target_mode and allow_downgrade is off.
    left_above_mode: bool


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


def _upsert_modes(organization_ids: Collection[UUID], mode: FlagEvaluationsMode, *, allow_downgrade: bool) -> set[UUID]:
    """Write the mode in one statement and return the ids of the rows it changed.

    The WHERE clause compares against the stored mode at write time. Without allow_downgrade, a
    concurrent write that raised an organization above `mode` after the caller read it is kept.
    """
    if not organization_ids:
        return set()
    table = OrganizationFeatureFlagsConfig._meta.db_table
    comparison = "<>" if allow_downgrade else "<"
    query = f"""
        INSERT INTO {table} (organization_id, flag_evaluations_mode)
        SELECT unnest(%s::uuid[]), %s
        ON CONFLICT (organization_id) DO UPDATE
           SET flag_evaluations_mode = EXCLUDED.flag_evaluations_mode
         WHERE {table}.flag_evaluations_mode {comparison} EXCLUDED.flag_evaluations_mode
        RETURNING organization_id
    """
    # The statement locks existing rows in the order of the array, so every writer sorts the ids to lock
    # overlapping rows in the same order.
    with connection.cursor() as cursor:
        cursor.execute(query, [[str(organization_id) for organization_id in sorted(organization_ids)], int(mode)])
        return {row[0] for row in cursor.fetchall()}


def set_organizations_flag_evaluations_mode(
    organizations: Sequence[Organization],
    mode: FlagEvaluationsMode,
    *,
    allow_downgrade: bool,
    dry_run: bool,
    count_experiments: bool = True,
) -> list[OrganizationModeChange]:
    """Move the organizations to `mode`, in the order given.

    An organization above `mode` stays where it is unless `allow_downgrade` is set. Lowering an
    organization from FLAG_EVALUATIONS_ONLY restarts events writes and leaves a gap in the events
    table.

    The reads and the write take one statement each for the whole list. Only the experiments count
    runs once per organization. `count_experiments=False` skips it and reports 0.

    Opens no transaction. A caller that must apply the whole list or none of it wraps the call.
    """
    organization_ids = [organization.id for organization in organizations]
    if len(set(organization_ids)) != len(organization_ids):
        raise ValueError("Each organization must appear once")
    current_modes = get_organization_flag_evaluations_modes(organization_ids)
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
        for organization_id, current_mode in current_modes.items()
        if current_mode < mode or (allow_downgrade and current_mode > mode)
    }
    changed_ids = moving_ids if dry_run else _upsert_modes(moving_ids, mode, allow_downgrade=allow_downgrade)
    return [
        OrganizationModeChange(
            organization_id=organization.id,
            organization_name=organization.name,
            organization_created_at=organization.created_at,
            team_count=team_counts.get(organization.id, 0),
            running_experiments_needing_flag_calls_in_events=(
                count_running_experiments_needing_flag_calls_in_events(organization.id) if count_experiments else 0
            ),
            current_mode=current_modes[organization.id],
            target_mode=mode,
            changed=organization.id in changed_ids,
            left_above_mode=current_modes[organization.id] > mode and not allow_downgrade,
        )
        for organization in organizations
    ]
