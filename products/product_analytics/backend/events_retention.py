from collections.abc import Sequence
from datetime import datetime, time

from django.core.exceptions import ValidationError
from django.db import transaction

from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.events_plan_deletion import (
    TeamEventsPlanDeletion,
    admitted,
    cleanup_date,
    next_cleanup_on,
    retention_window,
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
from posthog.models.team.event_retention import events_deletion_applies, organization_events_retention_months
from posthog.models.user import User

from products.product_analytics.backend.facade.contracts import (
    OrganizationEventsRetention,
    ProjectEventsRetention,
    ScheduledEventsDeletion,
)


def organization_events_retention(organization: Organization) -> OrganizationEventsRetention:
    config = OrganizationEventsRetentionConfig.objects.filter(organization_id=organization.id).first()
    plan_months = organization_events_retention_months(organization)
    staff_max = config.max_events_retention_months if config else None
    return OrganizationEventsRetention(
        organization_months=config.default_events_retention_months if config else None,
        organization_delete_monthly=config.delete_monthly if config else False,
        plan_months=plan_months,
        default_months=retention_window(plan_months, None),
        min_months=(config.min_events_retention_months if config else None) or 1,
        max_months=min(plan_months, staff_max) if staff_max else plan_months,
        next_cleanup_on=next_cleanup_on(),
    )


def _next_deletion(team: Team, setting: TeamEventsRetention | None) -> ScheduledEventsDeletion | None:
    setting_months = setting.months if setting else None
    if setting is not None and setting.delete_monthly:
        deletes_on, months = next_cleanup_on(), setting.months
    elif not events_deletion_applies(team.id, setting_months):
        return None
    else:
        row = TeamEventsPlanDeletion.objects.filter(team_id=team.id).first()
        if row is None:
            return None
        months = retention_window(team.event_retention_months, setting_months)
        deletes_on = with_window(row.state, months, cleanup_date()).next_deletion_on
    deletes_before = whole_month_cutoff(datetime.combine(deletes_on, time()), months).date()
    return ScheduledEventsDeletion(deletes_on=deletes_on, deletes_before=deletes_before)


def project_events_retention(team: Team) -> ProjectEventsRetention:
    project_months = (
        TeamEventsRetentionConfig.objects.filter(team_id=team.id)
        .values_list("events_retention_months", flat=True)
        .first()
    )
    setting = next(iter(effective_events_retention(team_ids=[team.id])), None)
    return ProjectEventsRetention(
        project_months=project_months,
        delete_monthly=setting.delete_monthly if setting else False,
        next_deletion=_next_deletion(team, setting),
    )


def _check_allowed(retention: OrganizationEventsRetention, months: int | None, delete_monthly: bool) -> None:
    if months is not None and not retention.min_months <= months <= retention.max_months:
        raise ValidationError(
            f"Events retention has to be {describe_months_range(retention.min_months, retention.max_months)}."
        )
    if delete_monthly and months is None:
        raise ValidationError("Set a window to delete events every month.")


def _schedule_passes(teams: Sequence[Team]) -> None:
    """Give each team whose window the cleanup enforces a pass date, so that its next deletion is known on save."""
    today = cleanup_date()
    team_ids = [team.id for team in teams]
    setting_months = {item.team_id: item.months for item in effective_events_retention(team_ids=team_ids)}
    states = {row.team_id: row.state for row in TeamEventsPlanDeletion.objects.filter(team_id__in=team_ids)}
    rows = []
    for team in teams:
        months = setting_months.get(team.id)
        if not events_deletion_applies(team.id, months):
            continue
        window = retention_window(team.event_retention_months, months)
        state = with_window(states[team.id], window, today) if team.id in states else admitted(window, today)
        rows.append(TeamEventsPlanDeletion(team=team, months=state.months, next_deletion_on=state.next_deletion_on))
    TeamEventsPlanDeletion.objects.bulk_create(
        rows, update_conflicts=True, unique_fields=["team"], update_fields=["months", "next_deletion_on"]
    )


def set_organization_events_retention(
    organization: Organization, months: int | None, delete_monthly: bool, *, user: User, was_impersonated: bool
) -> None:
    with transaction.atomic():
        # Lock before reading, because save() writes the staff range too and must not write back a stale one.
        lock_organization_retention(organization.id)
        config = OrganizationEventsRetentionConfig.objects.filter(organization_id=organization.id).first()
        before = (config.default_events_retention_months, config.delete_monthly) if config else (None, False)
        if (months, delete_monthly) == before:
            return
        _check_allowed(organization_events_retention(organization), months, delete_monthly)
        config = config or OrganizationEventsRetentionConfig(organization_id=organization.id)
        config.default_events_retention_months = months
        config.delete_monthly = delete_monthly
        config.full_clean()
        if months is None and config.min_events_retention_months is None and config.max_events_retention_months is None:
            config.delete()
        else:
            config.save()
        _schedule_passes(list(Team.objects.filter(organization_id=organization.id)))

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
            changes=_changes("Organization", "events retention", before, (months, delete_monthly)),
        ),
    )


def set_project_events_retention(
    team: Team, months: int | None, delete_monthly: bool, *, user: User, was_impersonated: bool
) -> None:
    with transaction.atomic():
        config = TeamEventsRetentionConfig.objects.filter(team_id=team.id).first()
        before = (config.events_retention_months, config.delete_monthly) if config else (None, False)
        if (months, delete_monthly) == before:
            return
        _check_allowed(organization_events_retention(team.organization), months, delete_monthly)
        if months is None:
            TeamEventsRetentionConfig.objects.filter(team_id=team.id).delete()
        else:
            config = config or TeamEventsRetentionConfig(team=team)
            config.events_retention_months = months
            config.delete_monthly = delete_monthly
            config.full_clean()
            config.save()
        _schedule_passes([team])

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
            changes=_changes("Team", "events_retention_months", before, (months, delete_monthly)),
        ),
    )


def _changes(
    scope: str, months_field: str, before: tuple[int | None, bool], after: tuple[int | None, bool]
) -> list[Change]:
    fields = (months_field, "events_retention_delete_monthly")
    return [
        Change(type=scope, action="changed", field=field, before=old, after=new)
        for field, old, new in zip(fields, before, after, strict=True)
        if old != new
    ]
