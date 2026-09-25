"""Organization-wide writes and audits for TeamFeatureFlagsConfig.flag_evaluations_mode.

A mode is meant to be uniform across an organization. TeamFeatureFlagsConfig.default_values_for_team
gives a new team the highest mode of its siblings, so the next project of a mixed organization takes
the highest mode among its teams. These helpers write every team of an organization together, and
find the organizations where that did not hold. Staff can also write a subset of an organization's
teams, which leaves that organization mixed.
"""

from collections import defaultdict
from collections.abc import Collection, Sequence
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
    organization_name: str
    organization_created_at: datetime
    organization_team_count: int
    # The teams the change covers. The counts below are over these teams only.
    team_count: int
    # Teams below the target mode. The write raises them.
    teams_below_mode: int
    teams_at_mode: int
    # Teams above the target mode. The write lowers them only when downgrades are allowed.
    teams_above_mode: int
    # Teams the write moved to the target mode. A dry run counts the teams it would move.
    teams_changed: int
    teams_left_above_mode: int


@frozen
class MixedModeOrganization:
    organization_id: UUID
    team_count_by_mode: dict[int, int]


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


def _stored_modes(teams: list[Team]) -> dict[int, int]:
    """Mode per team id, for the teams that have a config row."""
    return dict(
        TeamFeatureFlagsConfig.objects.filter(team_id__in=[team.id for team in teams]).values_list(
            "team_id", "flag_evaluations_mode"
        )
    )


def set_organization_flag_evaluations_mode(
    organization: Organization,
    mode: FlagEvaluationsMode,
    *,
    allow_downgrade: bool,
    dry_run: bool,
    team_ids: Collection[int] | None = None,
) -> OrganizationModeChange:
    """Move every team of the organization to `mode`, or only the teams in `team_ids`.

    A team above `mode` stays where it is unless `allow_downgrade` is set. Once ingestion supports
    FLAG_EVALUATIONS_ONLY, lowering a team from it restarts events writes and leaves a gap in the
    events table. The write is atomic, so a failure partway leaves every team on its old mode.
    """
    organization_teams = list(
        Team.objects.filter(organization_id=organization.id).only("id", "organization_id").order_by("id")
    )
    covered_team_ids = None if team_ids is None else set(team_ids)
    teams = [team for team in organization_teams if covered_team_ids is None or team.id in covered_team_ids]
    stored_modes = _stored_modes(teams)
    # A team without a config row reads EVENTS, the same as every reader.
    modes = {team.id: stored_modes.get(team.id, FlagEvaluationsMode.EVENTS) for team in teams}
    teams_to_write = [team for team in teams if modes[team.id] < mode or (allow_downgrade and modes[team.id] > mode)]
    teams_changed = len(teams_to_write)

    if not dry_run and teams_to_write:
        with transaction.atomic():
            # A new row starts at EVENTS, the mode the team reads without a row, so the UPDATE below
            # moves it and counts it. A per-team create opens a savepoint inside this transaction. Past
            # 64 savepoints that write, Postgres slows row visibility checks for every other session
            # until this transaction commits.
            TeamFeatureFlagsConfig.objects.bulk_create(
                [
                    TeamFeatureFlagsConfig(team=team, flag_evaluations_mode=FlagEvaluationsMode.EVENTS)
                    for team in teams_to_write
                    if team.id not in stored_modes
                ],
                ignore_conflicts=True,
            )
            update = TeamFeatureFlagsConfig.objects.filter(team_id__in=[team.id for team in teams_to_write])
            if not allow_downgrade:
                # Rechecked in the UPDATE because a staff write can raise a team after the read above.
                update = update.filter(flag_evaluations_mode__lt=mode)
            teams_changed = update.update(flag_evaluations_mode=mode)

    teams_above_mode = sum(1 for team in teams if modes[team.id] > mode)
    return OrganizationModeChange(
        organization_id=organization.id,
        organization_name=organization.name,
        organization_created_at=organization.created_at,
        organization_team_count=len(organization_teams),
        team_count=len(teams),
        teams_below_mode=sum(1 for team in teams if modes[team.id] < mode),
        teams_at_mode=sum(1 for team in teams if modes[team.id] == mode),
        teams_above_mode=teams_above_mode,
        teams_changed=teams_changed,
        teams_left_above_mode=0 if allow_downgrade else teams_above_mode,
    )


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
