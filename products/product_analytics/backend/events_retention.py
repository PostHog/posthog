from functools import partial
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.db import transaction

from posthog.event_usage import get_request_analytics_properties, report_user_action, sanitize_header_value
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.events_retention_config import (
    OrganizationEventsRetentionConfig,
    TeamEventsRetentionConfig,
    describe_months_range,
    lock_organization_retention,
)
from posthog.models.organization import Organization
from posthog.models.team import Team
from posthog.models.team.event_retention import organization_events_retention_months
from posthog.models.user import User

from products.product_analytics.backend.facade.contracts import OrganizationEventsRetention

if TYPE_CHECKING:
    from rest_framework.request import Request


def _report_retention_set(
    organization: Organization,
    team: Team | None,
    user: User,
    before: int | None,
    months: int | None,
    request: "Request | None",
) -> None:
    properties = {
        "scope": "project" if team else "organization",
        "organization_id": str(organization.id),
        "retention_months": months,
        "previous_retention_months": before,
        **(get_request_analytics_properties(request) if request else {"source": "unknown"}),
    }
    if team:
        properties["project_id"] = team.id
    if request:
        for property_name, header in (
            ("$mcp_session_id", "X-Posthog-Mcp-Session-Id"),
            ("$mcp_conversation_id", "X-Posthog-Mcp-Conversation-Id"),
            ("$ai_trace_id", "X-PostHog-Trace-Id"),
        ):
            if value := sanitize_header_value(request.headers.get(header)):
                properties[property_name] = value
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
    staff_max = config.max_events_retention_months if config else None
    return OrganizationEventsRetention(
        organization_months=config.default_events_retention_months if config else None,
        plan_months=plan_months,
        min_months=(config.min_events_retention_months if config else None) or 1,
        max_months=min(plan_months, staff_max) if staff_max else plan_months,
    )


def project_events_retention_months(team: Team) -> int | None:
    return (
        TeamEventsRetentionConfig.objects.filter(team_id=team.id)
        .values_list("events_retention_months", flat=True)
        .first()
    )


def _check_allowed(retention: OrganizationEventsRetention, months: int | None) -> None:
    if months is not None and not retention.min_months <= months <= retention.max_months:
        raise ValidationError(
            f"Events retention has to be {describe_months_range(retention.min_months, retention.max_months)}."
        )


def set_organization_events_retention(
    organization: Organization,
    months: int | None,
    *,
    user: User,
    was_impersonated: bool,
    request: "Request | None" = None,
) -> None:
    with transaction.atomic():
        # Lock before reading, because save() writes the staff range too and must not write back a stale one.
        lock_organization_retention(organization.id)
        config = OrganizationEventsRetentionConfig.objects.filter(organization_id=organization.id).first()
        before = config.default_events_retention_months if config else None
        if months == before:
            return
        _check_allowed(organization_events_retention(organization), months)
        config = config or OrganizationEventsRetentionConfig(organization_id=organization.id)
        config.default_events_retention_months = months
        config.full_clean()
        if months is None and config.min_events_retention_months is None and config.max_events_retention_months is None:
            config.delete()
        else:
            config.save()
        _report_retention_set(organization, None, user, before, months, request)

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
    request: "Request | None" = None,
) -> None:
    with transaction.atomic():
        config = TeamEventsRetentionConfig.objects.filter(team_id=team.id).first()
        before = config.events_retention_months if config else None
        if months == before:
            return
        _check_allowed(organization_events_retention(team.organization), months)
        if months is None:
            TeamEventsRetentionConfig.objects.filter(team_id=team.id).delete()
        else:
            config = config or TeamEventsRetentionConfig(team=team)
            config.events_retention_months = months
            config.full_clean()
            config.save()
        _report_retention_set(team.organization, team, user, before, months, request)

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
