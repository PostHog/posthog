from collections.abc import Sequence
from datetime import date, datetime, time
from functools import partial

from django.core.exceptions import ValidationError
from django.db import transaction

from posthog.event_usage import EventSource, report_user_action, sanitize_header_value
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.events_plan_deletion import (
    TeamEventsPlanDeletion,
    cleanup_date,
    deletion_months,
    next_cleanup_on,
    next_pass_on,
    reschedule_plan_deletions,
    with_window,
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
    STANDARD_DEFAULT_WINDOW_MONTHS,
    TeamPlan,
    default_window,
    events_retention_windows,
    has_standard_retention,
    organization_events_retention_months,
    should_enforce_events_retention,
    team_plan,
)
from posthog.models.user import User

from products.product_analytics.backend.facade.contracts import (
    OrganizationEventsRetention,
    ProjectEventsRetention,
    ScheduledEventsDeletion,
)

RETENTION_MONTHS_CHOICES = (1, 3, 12, 24, 36, 60, 84)


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
        default_months=default_window(plan_months, standard, staff_min),
        default_is_grandfathered=not standard and plan_months > STANDARD_DEFAULT_WINDOW_MONTHS,
        plan_months=plan_months,
        min_months=staff_min or 1,
        max_months=min(plan_months, staff_max) if staff_max else plan_months,
        months_choices=list(RETENTION_MONTHS_CHOICES),
        next_cleanup_on=next_cleanup_on(),
    )


def _next_deletion(
    team_id: int, setting: TeamEventsRetention | None, window_months: int, scheduled_pass_on: date | None
) -> ScheduledEventsDeletion | None:
    pass_on = (
        max(scheduled_pass_on, next_cleanup_on())
        if scheduled_pass_on is not None and should_enforce_events_retention(team_id)
        else None
    )
    deletes_on = next_cleanup_on() if setting is not None else pass_on
    if deletes_on is None:
        return None
    months = deletion_months(setting, window_months if pass_on is not None and pass_on <= deletes_on else None)
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
    window_months = events_retention_windows([team])[team.id]
    today = cleanup_date()
    row = TeamEventsPlanDeletion.objects.filter(team_id=team.id).first()
    scheduled_pass_on = with_window(row.state, window_months, today).next_deletion_on if row else None
    return ProjectEventsRetention(
        project_months=project_months,
        next_deletion=_next_deletion(team.id, setting, window_months, scheduled_pass_on),
        scheduled_pass_on=scheduled_pass_on,
        first_pass_on=next_pass_on(today),
        default_window_deletes=should_enforce_events_retention(team.id),
    )


def _check_allowed(retention: OrganizationEventsRetention, months: int | None) -> None:
    if months is None:
        return
    if months not in retention.months_choices:
        *shorter, longest = retention.months_choices
        raise ValidationError(
            f"Events retention has to be {', '.join(map(str, shorter))} or {longest} months. "
            "Contact PostHog support to set another period."
        )
    if not retention.min_months <= months <= retention.max_months:
        raise ValidationError(
            f"Events retention has to be {describe_months_range(retention.min_months, retention.max_months)}."
        )


def _enforced_plans(teams: Sequence[Team]) -> list[TeamPlan]:
    return [team_plan(team) for team in teams if should_enforce_events_retention(team.id)]


def _schedule_passes(plans: Sequence[TeamPlan]) -> None:
    reschedule_plan_deletions(plans, cleanup_date(), admit={plan.team_id for plan in plans})


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
        plans = _enforced_plans(Team.objects.filter(organization_id=organization.id))
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
        plans = _enforced_plans([team])
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
