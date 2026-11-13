from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from functools import partial
from typing import Literal, TypeVar
from uuid import UUID

from django.db import transaction
from django.db.models import CharField, Exists, OuterRef, Q, QuerySet
from django.db.models.functions import Cast

from posthog.models import Team
from posthog.models.activity_logging.activity_log import ActivityLog, field_name_overrides

from products.signals.backend.models import AutonomyPriority, SignalScoutConfig, SignalSourceConfig, SignalTeamConfig
from products.signals.backend.trial.policy import (
    TrialFlagDecision,
    TrialPolicy,
    activated_before_pricing_launch,
    spend_billing_starts_later,
)

GRANDFATHERED_AUTOSTART_PRIORITY = AutonomyPriority.P2

_Row = TypeVar("_Row", SignalTeamConfig, Team)

OrganizationOutcome = Literal[
    "grandfathered", "activated_after_launch", "billing_cutover_pending", "flag_unconfirmed", "usage_based_pricing"
]


def organization_outcome(
    *, activated_before_launch: bool, billing_cutover_pending: bool, flag: TrialFlagDecision
) -> OrganizationOutcome:
    if not activated_before_launch:
        return "activated_after_launch"
    # The flag also reads as off before the billing cutover date, and that does not make the plan grandfathered.
    if billing_cutover_pending:
        return "billing_cutover_pending"
    # A cached or missing answer can be stale, and this write is not undone by a later run.
    if not flag.confirmed or flag.enabled is None:
        return "flag_unconfirmed"
    return "usage_based_pricing" if flag.enabled else "grandfathered"


@dataclass(frozen=False)
class PriorityBackfillSummary:
    outcomes: Counter[str] = field(default_factory=Counter)
    team_ids: list[int] = field(default_factory=list)


def unchosen_autostart_priority_configs(*, team_id: int | None = None) -> QuerySet[SignalTeamConfig]:
    """Configs with automatic pull requests on and the P4 threshold that no person chose.

    P4 is the column default, so the value alone does not show a choice. Two records do: the
    setup flow stores the priority the person picked in the onboarding draft, and the activity
    log has an entry for each change a person made to the threshold.
    """
    logged_name = field_name_overrides["SignalTeamConfig"]["default_autostart_priority"]
    person_changed_priority = ActivityLog.objects.filter(
        team_id=OuterRef("team_id"),
        scope="SignalTeamConfig",
        item_id=Cast(OuterRef("pk"), output_field=CharField()),
        activity="updated",
        is_system=False,
        detail__changes__contains=[{"field": logged_name}],
    )
    # A subquery and not `exclude` on the JSON path: a row with no draft priority compares as NULL,
    # and `NOT NULL` drops the row.
    picked_p4_in_setup = SignalTeamConfig.objects.filter(
        pk=OuterRef("pk"), onboarding__draft__implementation_priority=AutonomyPriority.P4
    )
    configs = SignalTeamConfig.objects.filter(
        Q(autostart_enabled__isnull=True) | Q(autostart_enabled=True),
        ~Exists(picked_p4_in_setup),
        ~Exists(person_changed_priority),
        default_autostart_priority=AutonomyPriority.P4,
    )
    if team_id is not None:
        configs = configs.filter(team_id=team_id)
    return configs


def teams_without_config(*, team_id: int | None = None) -> QuerySet[Team]:
    """Projects that run a signal source or scout and have no config row.

    Auto-start treats a missing row as automatic pull requests on with the P4 threshold. Projects
    that never ran self-driving produce no reports, so they get no row.
    """
    teams = Team.objects.filter(
        Exists(SignalSourceConfig.objects.filter(team_id=OuterRef("pk")))
        | Exists(SignalScoutConfig.objects.unscoped().filter(team_id=OuterRef("pk"))),
        ~Exists(SignalTeamConfig.objects.filter(team_id=OuterRef("pk"))),
    )
    if team_id is not None:
        teams = teams.filter(pk=team_id)
    return teams


def _organization_outcome_for(team: Team) -> OrganizationOutcome:
    organization_id = team.organization_id
    activated = activated_before_pricing_launch(organization_id)
    cutover_pending = activated and spend_billing_starts_later(organization_id)
    flag = (
        TrialPolicy(team).flag_decision()
        if activated and not cutover_pending
        else TrialFlagDecision(enabled=None, confirmed=False)
    )
    return organization_outcome(activated_before_launch=activated, billing_cutover_pending=cutover_pending, flag=flag)


def _apply_priority(config: SignalTeamConfig) -> bool:
    with transaction.atomic():
        locked = (
            unchosen_autostart_priority_configs(team_id=config.team_id).select_for_update().filter(pk=config.pk).first()
        )
        if locked is None:
            return False
        locked.default_autostart_priority = GRANDFATHERED_AUTOSTART_PRIORITY
        # `save` and not a queryset update, so that the activity log records the change.
        locked.save(update_fields=["default_autostart_priority", "updated_at"])
        return True


def _create_config(team: Team) -> bool:
    # A row created since the selection may hold a person's choice, so it is left alone.
    _, created = SignalTeamConfig.objects.get_or_create(
        team_id=team.pk, defaults={"default_autostart_priority": GRANDFATHERED_AUTOSTART_PRIORITY}
    )
    return created


def _batches(rows: QuerySet[_Row], batch_size: int) -> Iterator[list[_Row]]:
    after_pk = None
    while True:
        page = rows.order_by("pk")
        if after_pk is not None:
            page = page.filter(pk__gt=after_pk)
        batch = list(page[:batch_size])
        if not batch:
            return
        yield batch
        after_pk = batch[-1].pk


def backfill_grandfathered_autostart_priority(
    *, apply: bool, team_id: int | None, batch_size: int
) -> PriorityBackfillSummary:
    summary = PriorityBackfillSummary()
    organization_outcomes: dict[UUID, OrganizationOutcome] = {}

    def record(team: Team, write: Callable[[], bool], written: str) -> None:
        if team.organization_id not in organization_outcomes:
            organization_outcomes[team.organization_id] = _organization_outcome_for(team)
        outcome: str = organization_outcomes[team.organization_id]
        if outcome == "grandfathered":
            summary.team_ids.append(team.pk)
            if apply:
                outcome = written if write() else "changed_during_run"
        summary.outcomes[outcome] += 1

    configs = unchosen_autostart_priority_configs(team_id=team_id).select_related("team")
    for config_batch in _batches(configs, batch_size):
        for config in config_batch:
            record(config.team, partial(_apply_priority, config), "updated")
    for team_batch in _batches(teams_without_config(team_id=team_id), batch_size):
        for team in team_batch:
            record(team, partial(_create_config, team), "created")
    return summary
