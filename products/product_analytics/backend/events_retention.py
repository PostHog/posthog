from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime, time

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import transaction

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.workload import Workload
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.events_plan_deletion import (
    TeamEventsPlanDeletion,
    cleanup_date,
    deletion_months,
    next_cleanup_on,
    next_pass_on,
    reschedule_plan_deletions,
    with_period,
)
from posthog.models.events_retention_config import (
    OrganizationEventsRetentionConfig,
    TeamEventsRetention,
    TeamEventsRetentionConfig,
    describe_months_range,
    effective_events_retention,
    lock_organization_retention,
    whole_month_cutoff,
)
from posthog.models.organization import Organization
from posthog.models.team import Team
from posthog.models.team.event_retention import (
    STANDARD_DEFAULT_PERIOD_MONTHS,
    TeamPlan,
    default_period,
    events_retention_periods,
    has_standard_retention,
    organization_events_retention_months,
    should_delete_past_default_period,
    team_plan,
)
from posthog.models.user import User

from products.product_analytics.backend.facade.contracts import (
    OrganizationEventsRetention,
    ProjectEventsRetention,
    ScheduledEventsDeletion,
)

# Only staff can set a period outside these, e.g. for a contract.
RETENTION_CHOICE_MONTHS = (1, 3, 12, 24, 60, 84)

IMPACT_CACHE_SECONDS = 60 * 60 * 24


def organization_events_retention(organization: Organization) -> OrganizationEventsRetention:
    config = OrganizationEventsRetentionConfig.objects.filter(organization_id=organization.id).first()
    plan_months = organization_events_retention_months(organization)
    staff_min = config.min_events_retention_months if config else None
    staff_max = config.max_events_retention_months if config else None
    standard = has_standard_retention(organization)
    min_months = staff_min or 1
    max_months = min(plan_months, staff_max) if staff_max else plan_months
    return OrganizationEventsRetention(
        organization_months=config.default_events_retention_months if config else None,
        default_months=default_period(plan_months, standard, staff_min),
        default_is_grandfathered=not standard and plan_months > STANDARD_DEFAULT_PERIOD_MONTHS,
        plan_months=plan_months,
        min_months=min_months,
        max_months=max_months,
        choice_months=[months for months in RETENTION_CHOICE_MONTHS if min_months <= months <= max_months],
        next_cleanup_on=next_cleanup_on(),
    )


def _next_deletion(
    setting: TeamEventsRetention | None, period_months: int, scheduled_pass_on: date | None
) -> ScheduledEventsDeletion | None:
    pass_on = max(scheduled_pass_on, next_cleanup_on()) if scheduled_pass_on is not None else None
    deletes_on = next_cleanup_on() if setting is not None else pass_on
    if deletes_on is None:
        return None
    months = deletion_months(setting, period_months if pass_on is not None and pass_on <= deletes_on else None)
    if months is None:
        return None
    deletes_before = whole_month_cutoff(datetime.combine(deletes_on, time()), months).date()
    return ScheduledEventsDeletion(deletes_on=deletes_on, deletes_before=deletes_before)


def project_events_retention(team: Team) -> ProjectEventsRetention:
    project_months = (
        TeamEventsRetentionConfig.objects.filter(team_id=team.id)
        .values_list("events_retention_months", flat=True)
        .first()
    )
    setting = next(iter(effective_events_retention(team_ids=[team.id])), None)
    period_months = events_retention_periods([team])[team.id]
    today = cleanup_date()
    row = TeamEventsPlanDeletion.objects.filter(team_id=team.id).first()
    scheduled_pass_on = with_period(row.state, period_months, today).next_deletion_on if row else None
    default_period_deletes = should_delete_past_default_period(team)
    return ProjectEventsRetention(
        project_months=project_months,
        next_deletion=_next_deletion(setting, period_months, scheduled_pass_on if default_period_deletes else None),
        scheduled_pass_on=scheduled_pass_on,
        first_pass_on=next_pass_on(today),
        default_period_deletes=default_period_deletes,
    )


def _describe_choices(choice_months: list[int]) -> str:
    if not choice_months:
        return "Contact PostHog support to change events retention."
    choices = [str(months) for months in choice_months]
    listed = f"{', '.join(choices[:-1])} or {choices[-1]}" if len(choices) > 1 else choices[0]
    return f"Events retention has to be {listed} months. Only PostHog staff can set other values."


def _check_allowed(retention: OrganizationEventsRetention, months: int | None, user: User) -> None:
    if months is None:
        return
    if not user.is_staff and months not in retention.choice_months:
        raise ValidationError(_describe_choices(retention.choice_months))
    if not retention.min_months <= months <= retention.max_months:
        raise ValidationError(
            f"Events retention has to be {describe_months_range(retention.min_months, retention.max_months)}."
        )


def project_events_deleted_by_retention(team: Team, months: int) -> int:
    """How many of the project's events the monthly cleanup would delete now, with this period."""
    cutoff = whole_month_cutoff(datetime.now(UTC).replace(tzinfo=None), months).replace(tzinfo=UTC)
    cache_key = f"events_retention_impact:{team.id}:{cutoff:%Y-%m}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    response = execute_hogql_query(
        "SELECT count() FROM events WHERE timestamp < {cutoff}",
        team=team,
        placeholders={"cutoff": ast.Constant(value=cutoff)},
        query_type="events_retention_impact",
        workload=Workload.ONLINE,
        # Events past the current period stay stored until the cleanup runs, so the count must include them.
        context=HogQLContext(team_id=team.pk, apply_events_retention_floor=False),
    )
    count = response.results[0][0]
    cache.set(cache_key, count, timeout=IMPACT_CACHE_SECONDS)
    return count


def organization_events_deleted_by_retention(organization: Organization, months: int) -> int:
    """How many events the monthly cleanup would delete now from the projects that use the organization's period."""
    teams = Team.objects.filter(organization_id=organization.id).exclude(
        id__in=TeamEventsRetentionConfig.objects.filter(team__organization_id=organization.id).values("team_id")
    )
    return sum(project_events_deleted_by_retention(team, months) for team in teams)


def _deleting_plans(teams: Iterable[Team]) -> list[TeamPlan]:
    return [team_plan(team) for team in teams if should_delete_past_default_period(team)]


def _schedule_passes(plans: Sequence[TeamPlan]) -> None:
    reschedule_plan_deletions(plans, cleanup_date())


def set_organization_events_retention(
    organization: Organization, months: int | None, *, user: User, was_impersonated: bool
) -> None:
    with transaction.atomic():
        # Lock before reading, because save() writes the staff range too and must not write back a stale one.
        lock_organization_retention(organization.id)
        config = OrganizationEventsRetentionConfig.objects.filter(organization_id=organization.id).first()
        before = config.default_events_retention_months if config else None
        if months == before:
            return
        _check_allowed(organization_events_retention(organization), months, user)
        plans = _deleting_plans(Team.objects.filter(organization_id=organization.id))
        _schedule_passes(plans)
        config = config or OrganizationEventsRetentionConfig(organization_id=organization.id)
        config.default_events_retention_months = months
        config.full_clean()
        if months is None and config.min_events_retention_months is None and config.max_events_retention_months is None:
            config.delete()
        else:
            config.save()
        _schedule_passes(plans)

    log_activity(
        organization_id=organization.id,
        team_id=None,
        user=user,
        was_impersonated=was_impersonated,
        scope="Organization",
        item_id=str(organization.id),
        activity="updated",
        detail=Detail(
            name=organization.name,
            changes=[
                Change(type="Organization", action="changed", field="events retention", before=before, after=months)
            ],
        ),
    )


def set_project_events_retention(team: Team, months: int | None, *, user: User, was_impersonated: bool) -> None:
    with transaction.atomic():
        lock_organization_retention(team.organization_id)
        config = TeamEventsRetentionConfig.objects.filter(team_id=team.id).first()
        before = config.events_retention_months if config else None
        if months == before:
            return
        _check_allowed(organization_events_retention(team.organization), months, user)
        plans = _deleting_plans([team])
        _schedule_passes(plans)
        if months is None:
            TeamEventsRetentionConfig.objects.filter(team_id=team.id).delete()
        else:
            config = config or TeamEventsRetentionConfig(team=team)
            config.events_retention_months = months
            config.full_clean()
            config.save()
        _schedule_passes(plans)

    log_activity(
        organization_id=team.organization_id,
        team_id=team.id,
        user=user,
        was_impersonated=was_impersonated,
        scope="Team",
        item_id=team.id,
        activity="updated",
        detail=Detail(
            name=team.name,
            changes=[
                Change(type="Team", action="changed", field="events_retention_months", before=before, after=months)
            ],
        ),
    )
