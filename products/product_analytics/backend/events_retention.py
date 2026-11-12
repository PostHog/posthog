import math
from collections.abc import Callable, Iterable, Sequence
from contextlib import AbstractContextManager
from datetime import UTC, date, datetime, time
from functools import partial
from time import monotonic

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import transaction

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.event_usage import EventSource, report_user_action, sanitize_header_value
from posthog.exceptions import ClickHouseQueryTimeOut
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.events_plan_deletion import (
    TeamEventsPlanDeletion,
    cleanup_date,
    deleting_plans,
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
)
from posthog.models.user import User

from products.product_analytics.backend.facade.contracts import (
    OrganizationEventsRetention,
    ProjectEventsRetention,
    ScheduledEventsDeletion,
)
from products.product_analytics.backend.facade.enums import EventsRetentionMonths

NOT_A_STANDARD_PERIOD_MESSAGE = (
    f"Events retention has to be {', '.join(map(str, EventsRetentionMonths.values[:-1]))} or "
    f"{EventsRetentionMonths.values[-1]} months. Contact PostHog support to set another period."
)
EVENTS_DELETED_QUERY_SECONDS = 10
EVENTS_DELETED_CACHE_SECONDS = 24 * 60 * 60

ConcurrencySlots = Callable[[Team], AbstractContextManager[None]]


def _report_retention_set(
    organization: Organization,
    team: Team | None,
    user: User,
    before: int | None,
    months: int | None,
    analytics_properties: dict[str, object] | None,
    was_impersonated: bool,
) -> None:
    properties: dict[str, object] = {"source": "unknown"}
    for key in (
        "source",
        "$current_url",
        "$host",
        "$pathname",
        "$session_id",
        "access_method",
        "user_agent",
        "mcp_user_agent",
        "mcp_client_name",
        "mcp_client_version",
        "mcp_protocol_version",
        "mcp_oauth_client_name",
        "$mcp_session_id",
        "$mcp_conversation_id",
        "$ai_trace_id",
    ):
        value = (analytics_properties or {}).get(key)
        if isinstance(value, str) and (sanitized := sanitize_header_value(value)):
            properties[key] = sanitized
    if properties["source"] not in {source.value for source in EventSource}:
        properties["source"] = "unknown"
    properties.update(
        {
            "scope": "project" if team else "organization",
            "organization_id": str(organization.id),
            "retention_months": months,
            "previous_retention_months": before,
            "was_impersonated": was_impersonated,
        }
    )
    if team:
        properties["project_id"] = team.id
    transaction.on_commit(
        partial(
            report_user_action,
            user,
            "events retention set",
            properties,
            organization=organization,
            team=team,
        )
    )


def organization_events_retention(organization: Organization) -> OrganizationEventsRetention:
    config = OrganizationEventsRetentionConfig.objects.filter(organization_id=organization.id).first()
    plan_months = organization_events_retention_months(organization)
    staff_min = config.min_events_retention_months if config else None
    staff_max = config.max_events_retention_months if config else None
    standard = has_standard_retention(organization)
    return OrganizationEventsRetention(
        organization_months=config.default_events_retention_months if config else None,
        default_months=default_period(plan_months, standard, staff_min),
        default_is_grandfathered=not standard and plan_months > STANDARD_DEFAULT_PERIOD_MONTHS,
        plan_months=plan_months,
        min_months=staff_min or 1,
        max_months=min(plan_months, staff_max) if staff_max else plan_months,
        months_choices=list(EventsRetentionMonths.values),
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


def _cutoff_on(deletes_on: date, months: int) -> datetime:
    return whole_month_cutoff(datetime.combine(deletes_on, time()), months).replace(tzinfo=UTC)


def _events_before(team: Team, cutoff: datetime, seconds: int, concurrency_slots: ConcurrencySlots) -> int:
    key = f"events_retention_deleted:{team.id}:{cutoff:%Y-%m-%d}"
    if (count := cache.get(key)) is not None:
        return count
    if seconds <= 0:
        raise ClickHouseQueryTimeOut()
    with concurrency_slots(team):
        response = execute_hogql_query(
            "SELECT count() FROM events WHERE timestamp < {cutoff}",
            team,
            query_type="events_retention_deletion_count",
            placeholders={"cutoff": ast.Constant(value=cutoff)},
            workload=Workload.ONLINE,
            settings=HogQLGlobalSettings(max_execution_time=seconds, timeout_overflow_mode="throw"),
        )
    count = response.results[0][0]
    cache.set(key, count, EVENTS_DELETED_CACHE_SECONDS)
    return count


def _teams_events_before(teams: Iterable[Team], cutoff: datetime, concurrency_slots: ConcurrencySlots) -> int:
    deadline = monotonic() + EVENTS_DELETED_QUERY_SECONDS
    return sum(_events_before(team, cutoff, math.ceil(deadline - monotonic()), concurrency_slots) for team in teams)


def project_events_deleted(team: Team, months: int, *, concurrency_slots: ConcurrencySlots) -> int:
    return _events_before(team, _cutoff_on(next_cleanup_on(), months), EVENTS_DELETED_QUERY_SECONDS, concurrency_slots)


def project_events_deleted_before(team: Team, before: date, *, concurrency_slots: ConcurrencySlots) -> int:
    cutoff = datetime.combine(before, time(), tzinfo=UTC)
    return _events_before(team, cutoff, EVENTS_DELETED_QUERY_SECONDS, concurrency_slots)


def organization_events_deleted(organization: Organization, months: int, *, concurrency_slots: ConcurrencySlots) -> int:
    teams = Team.objects.filter(organization_id=organization.id).exclude(
        id__in=TeamEventsRetentionConfig.objects.filter(events_retention_months__isnull=False).values("team_id")
    )
    return _teams_events_before(teams, _cutoff_on(next_cleanup_on(), months), concurrency_slots)


def organization_downgrade_events_deleted(
    organization: Organization, months: int, *, concurrency_slots: ConcurrencySlots
) -> int:
    teams = list(Team.objects.filter(organization_id=organization.id))
    kept = {
        setting.team_id
        for setting in effective_events_retention(team_ids=[team.id for team in teams])
        if setting.months <= months
    }
    return _teams_events_before(
        [team for team in teams if team.id not in kept],
        _cutoff_on(next_pass_on(cleanup_date()), months),
        concurrency_slots,
    )


def _check_allowed(retention: OrganizationEventsRetention, months: int | None) -> None:
    if months is None:
        return
    if months not in retention.months_choices:
        raise ValidationError(NOT_A_STANDARD_PERIOD_MESSAGE)
    if not retention.min_months <= months <= retention.max_months:
        raise ValidationError(
            f"Events retention has to be {describe_months_range(retention.min_months, retention.max_months)}."
        )


def _schedule_passes(plans: Sequence[TeamPlan]) -> None:
    reschedule_plan_deletions(plans, cleanup_date())


def set_organization_events_retention(
    organization: Organization,
    months: int | None,
    *,
    user: User,
    was_impersonated: bool,
    analytics_properties: dict[str, object] | None = None,
) -> None:
    with transaction.atomic():
        # Lock before reading, because save() writes the staff range too and must not write back a stale one.
        lock_organization_retention(organization.id)
        config = OrganizationEventsRetentionConfig.objects.filter(organization_id=organization.id).first()
        before = config.default_events_retention_months if config else None
        if months == before:
            return
        _check_allowed(organization_events_retention(organization), months)
        plans = deleting_plans(Team.objects.filter(organization_id=organization.id))
        _schedule_passes(plans)
        config = config or OrganizationEventsRetentionConfig(organization_id=organization.id)
        config.default_events_retention_months = months
        config.full_clean()
        if months is None and config.min_events_retention_months is None and config.max_events_retention_months is None:
            config.delete()
        else:
            config.save()
        _report_retention_set(organization, None, user, before, months, analytics_properties, was_impersonated)
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


def set_project_events_retention(
    team: Team,
    months: int | None,
    *,
    user: User,
    was_impersonated: bool,
    analytics_properties: dict[str, object] | None = None,
) -> None:
    with transaction.atomic():
        lock_organization_retention(team.organization_id)
        config = TeamEventsRetentionConfig.objects.filter(team_id=team.id).first()
        before = config.events_retention_months if config else None
        if months == before:
            return
        _check_allowed(organization_events_retention(team.organization), months)
        plans = deleting_plans([team])
        _schedule_passes(plans)
        if months is None:
            TeamEventsRetentionConfig.objects.filter(team_id=team.id).delete()
        else:
            config = config or TeamEventsRetentionConfig(team=team)
            config.events_retention_months = months
            config.full_clean()
            config.save()
        _report_retention_set(team.organization, team, user, before, months, analytics_properties, was_impersonated)
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
