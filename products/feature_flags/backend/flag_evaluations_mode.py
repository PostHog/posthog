"""Organization-wide writes and audits for TeamFeatureFlagsConfig.flag_evaluations_mode.

A mode is meant to be uniform across an organization. TeamFeatureFlagsConfig.default_values_for_team
gives a new team the highest mode of its siblings, so the next project of a mixed organization takes
the highest mode among its teams. These helpers write every team of an organization together, and
find the organizations where that did not hold.
"""

from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from django.db import transaction
from django.db.models import Count, QuerySet

from posthog.dataclasses import frozen
from posthog.models import Organization, Team

from products.feature_flags.backend.models.team_feature_flags_config import (
    FlagEvaluationsMode,
    TeamFeatureFlagsConfig,
    flag_evaluations_mode_annotation,
)


@frozen
class OrganizationModeChange:
    organization_id: UUID
    organization_created_at: datetime
    team_count: int
    # Teams below the target mode. The write raises them.
    teams_below_mode: int
    teams_at_mode: int
    # Teams above the target mode. The write lowers them only when downgrades are allowed.
    teams_above_mode: int


@frozen
class MixedModeOrganization:
    organization_id: UUID
    team_count_by_mode: dict[int, int]


def select_organizations(
    *, organization_ids: Sequence[UUID] | None = None, created_after: datetime | None = None
) -> QuerySet[Organization]:
    """Exactly one selector: explicit ids, or every organization created after an instant."""
    if (organization_ids is None) == (created_after is None):
        raise ValueError("Pass exactly one of organization_ids and created_after")
    if organization_ids is not None:
        return Organization.objects.filter(id__in=organization_ids).order_by("created_at")
    return Organization.objects.filter(created_at__gt=created_after).order_by("created_at")


def _team_modes(teams: list[Team]) -> dict[int, int]:
    """Mode per team id. A team without a config row reads EVENTS, the same as every reader."""
    stored = dict(
        TeamFeatureFlagsConfig.objects.filter(team_id__in=[team.id for team in teams]).values_list(
            "team_id", "flag_evaluations_mode"
        )
    )
    return {team.id: stored.get(team.id, FlagEvaluationsMode.EVENTS) for team in teams}


def set_organization_flag_evaluations_mode(
    organization: Organization, mode: FlagEvaluationsMode, *, allow_downgrade: bool, dry_run: bool
) -> OrganizationModeChange:
    """Move every team of the organization to `mode`.

    A team above `mode` stays where it is unless `allow_downgrade` is set. Once ingestion supports
    FLAG_EVALUATIONS_ONLY, lowering a team from it restarts events writes and leaves a gap in the
    events table.

    A failure partway leaves every team on its old mode.
    """
    teams = list(Team.objects.filter(organization_id=organization.id).order_by("id"))
    modes = _team_modes(teams)
    teams_to_write = [team for team in teams if modes[team.id] < mode or (allow_downgrade and modes[team.id] > mode)]
    change = OrganizationModeChange(
        organization_id=organization.id,
        organization_created_at=organization.created_at,
        team_count=len(teams),
        teams_below_mode=sum(1 for team in teams if modes[team.id] < mode),
        teams_at_mode=sum(1 for team in teams if modes[team.id] == mode),
        teams_above_mode=sum(1 for team in teams if modes[team.id] > mode),
    )
    if dry_run or not teams_to_write:
        return change

    with transaction.atomic():
        # A per-team create opens a savepoint inside this transaction. Past 64 savepoints that write,
        # Postgres slows row visibility checks for every other session until this transaction commits.
        TeamFeatureFlagsConfig.objects.bulk_create(
            [TeamFeatureFlagsConfig(team=team, flag_evaluations_mode=mode) for team in teams_to_write],
            ignore_conflicts=True,
        )
        update = TeamFeatureFlagsConfig.objects.filter(team_id__in=[team.id for team in teams_to_write])
        if not allow_downgrade:
            # Rechecked in the UPDATE because a staff write can raise a team after the read above.
            update = update.filter(flag_evaluations_mode__lt=mode)
        update.update(flag_evaluations_mode=mode)
    return change


def find_mixed_mode_organizations() -> list[MixedModeOrganization]:
    """Every organization whose teams hold more than one mode, with the team count per mode."""
    teams_with_mode = Team.objects.annotate(mode=flag_evaluations_mode_annotation())
    mixed_organization_ids = list(
        teams_with_mode.order_by()
        .values("organization_id")
        .annotate(mode_count=Count("mode", distinct=True))
        .filter(mode_count__gt=1)
        .values_list("organization_id", flat=True)
    )
    if not mixed_organization_ids:
        return []

    team_count_by_mode: dict[UUID, dict[int, int]] = defaultdict(dict)
    for organization_id, mode, team_count in (
        teams_with_mode.filter(organization_id__in=mixed_organization_ids)
        .order_by()
        .values("organization_id", "mode")
        .annotate(team_count=Count("id"))
        .values_list("organization_id", "mode", "team_count")
    ):
        team_count_by_mode[organization_id][mode] = team_count
    return [
        MixedModeOrganization(organization_id=organization_id, team_count_by_mode=counts)
        for organization_id, counts in sorted(team_count_by_mode.items(), key=lambda item: str(item[0]))
    ]
