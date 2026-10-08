"""Writes of OrganizationFeatureFlagsConfig.flag_evaluations_mode, one organization at a time."""

from collections.abc import Collection, Sequence
from datetime import datetime
from uuid import UUID

from django.db import connection
from django.db.models import QuerySet

from posthog.dataclasses import frozen
from posthog.models import Organization, Team

from products.experiments.backend.facade import count_running_experiments_on_feature_flag_called
from products.feature_flags.backend.facade.enums import FlagEvaluationsMode
from products.feature_flags.backend.facade.flags import get_organization_flag_evaluations_mode
from products.feature_flags.backend.models.organization_feature_flags_config import OrganizationFeatureFlagsConfig


@frozen
class OrganizationModeChange:
    organization_id: UUID
    organization_name: str
    organization_created_at: datetime
    # Teams of the organization, for display only. The write never touches team rows.
    team_count: int
    # On FLAG_EVALUATIONS_ONLY these experiments stop gaining exposures for teams in the ingestion
    # allowlist, because ingestion stops writing $feature_flag_called to events for those teams.
    running_experiments_on_feature_flag_called: int
    current_mode: int
    target_mode: int
    # True when the write moved the organization to target_mode, or would on a dry run.
    changed: bool
    # True when the organization is above target_mode and allow_downgrade is off.
    left_above_mode: bool


class UnknownIdsError(Exception):
    def __init__(self, label: str, missing_ids: Collection[object]) -> None:
        super().__init__(f"Unknown {label} id(s): {', '.join(sorted(map(str, missing_ids)))}")


def select_organizations(
    *, organization_ids: Sequence[UUID] | None = None, created_after: datetime | None = None
) -> QuerySet[Organization]:
    """Exactly one selector: explicit ids, or every organization created after an instant."""
    if (organization_ids is None) == (created_after is None):
        raise ValueError("Pass exactly one of organization_ids and created_after")
    if organization_ids is not None:
        return Organization.objects.filter(id__in=organization_ids).order_by("created_at")
    return Organization.objects.filter(created_at__gt=created_after).order_by("created_at")


def get_organizations(organization_ids: Collection[UUID]) -> list[Organization]:
    """The given organizations, oldest first.

    Raises UnknownIdsError when an id does not exist, so that a caller refuses the whole request
    and names the bad id instead of skipping it.
    """
    organizations = list(select_organizations(organization_ids=list(organization_ids)))
    if missing_ids := set(organization_ids) - {organization.id for organization in organizations}:
        raise UnknownIdsError("organization", missing_ids)
    return organizations


def get_organizations_of_teams(team_ids: Collection[int]) -> list[Organization]:
    """The organizations that own the given teams, oldest first. Raises UnknownIdsError like get_organizations."""
    organization_id_by_team_id = dict(Team.objects.filter(id__in=team_ids).values_list("id", "organization_id"))
    if missing_ids := set(team_ids) - organization_id_by_team_id.keys():
        raise UnknownIdsError("team", missing_ids)
    return get_organizations(set(organization_id_by_team_id.values()))


def _upsert_mode(organization_id: UUID, mode: FlagEvaluationsMode, *, allow_downgrade: bool) -> bool:
    """Write the mode in one statement and report whether a row changed.

    The WHERE clause compares against the stored mode at write time. Without allow_downgrade, a
    concurrent write that raised the organization above `mode` after the caller read it is kept.
    """
    table = OrganizationFeatureFlagsConfig._meta.db_table
    comparison = "<>" if allow_downgrade else "<"
    query = f"""
        INSERT INTO {table} (organization_id, flag_evaluations_mode)
        VALUES (%s, %s)
        ON CONFLICT (organization_id) DO UPDATE
           SET flag_evaluations_mode = EXCLUDED.flag_evaluations_mode
         WHERE {table}.flag_evaluations_mode {comparison} EXCLUDED.flag_evaluations_mode
    """
    with connection.cursor() as cursor:
        cursor.execute(query, [organization_id, int(mode)])
        return cursor.rowcount == 1


def set_organization_flag_evaluations_mode(
    organization: Organization, mode: FlagEvaluationsMode, *, allow_downgrade: bool, dry_run: bool
) -> OrganizationModeChange:
    """Move the organization to `mode`.

    An organization above `mode` stays where it is unless `allow_downgrade` is set. Lowering an
    organization from FLAG_EVALUATIONS_ONLY restarts events writes and leaves a gap in the events
    table.

    Opens no transaction. A caller that writes several organizations wraps its own loop.
    """
    current_mode = get_organization_flag_evaluations_mode(organization.id)
    changed = current_mode < mode or (allow_downgrade and current_mode > mode)
    # The statement runs only when the read says the mode moves. A missing row reads EVENTS, so a
    # write of EVENTS to it would insert a row and report a change that no reader can see.
    if changed and not dry_run:
        changed = _upsert_mode(organization.id, mode, allow_downgrade=allow_downgrade)
    return OrganizationModeChange(
        organization_id=organization.id,
        organization_name=organization.name,
        organization_created_at=organization.created_at,
        team_count=Team.objects.filter(organization_id=organization.id).count(),
        running_experiments_on_feature_flag_called=count_running_experiments_on_feature_flag_called(organization.id),
        current_mode=current_mode,
        target_mode=mode,
        changed=changed,
        left_above_mode=current_mode > mode and not allow_downgrade,
    )
