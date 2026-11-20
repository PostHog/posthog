"""Monthly budget alert emails for the managed warehouse."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

from django.conf import settings
from django.db.models import Q

import structlog

from posthog.email import EmailMessage, get_email_team_and_org_context
from posthog.models import Organization, OrganizationMembership, Team

from products.managed_warehouse.backend.logic.console_access import is_console_enabled
from products.managed_warehouse.backend.logic.console_usage import SpendEstimate, estimate_month_to_date_spend
from products.managed_warehouse.backend.models import ManagedWarehouseOrgSettings

logger = structlog.get_logger(__name__)

BUDGET_THRESHOLDS = (50, 80, 100)


def highest_threshold_reached(spend: Decimal, budget: Decimal) -> int | None:
    reached = [pct for pct in BUDGET_THRESHOLDS if spend * 100 >= budget * pct]
    return max(reached) if reached else None


def _claim_alert(settings_id: object, budget: Decimal, month_start: object, threshold: int) -> bool:
    """Atomically record the alert. Only one caller per threshold and month gets True."""
    claimed = (
        ManagedWarehouseOrgSettings.objects.filter(pk=settings_id, monthly_budget_usd=budget)
        .filter(
            Q(budget_alert_month__isnull=True)
            | Q(budget_alert_month__lt=month_start)
            | Q(budget_alert_month=month_start, budget_alert_threshold__isnull=True)
            | Q(budget_alert_month=month_start, budget_alert_threshold__lt=threshold)
        )
        .update(budget_alert_month=month_start, budget_alert_threshold=threshold)
    )
    return claimed == 1


def _admin_users(organization_id: str) -> list:
    memberships = (
        OrganizationMembership.objects.select_related("user")
        .with_effective_level()
        .filter(
            organization_id=organization_id,
            user__is_active=True,
            resolved_level__gte=OrganizationMembership.Level.ADMIN,
        )
    )
    return [m.user for m in memberships if m.user.email]


def _send_alert_email(organization: Organization, *, threshold: int, budget: Decimal, estimate: SpendEstimate) -> None:
    team = Team.objects.filter(organization_id=organization.id).order_by("id").first()
    users = _admin_users(str(organization.id))
    if team is None or not users:
        return
    message = EmailMessage(
        # The budget is part of the key because the email service skips recipients already sent a key,
        # and a budget change starts a new alert cycle.
        campaign_key=(
            f"managed_warehouse_budget_{organization.id}_{estimate.month_start.isoformat()}"
            f"_{threshold}_{int(budget * 100)}"
        ),
        subject=f"Your warehouse spend reached {threshold}% of your monthly budget",
        template_name="managed_warehouse_budget_alert",
        template_context={
            "threshold": threshold,
            "spend": f"{estimate.total_usd:,.2f}",
            "budget": f"{budget:,.2f}",
            "forecast": f"{estimate.forecast_usd:,.2f}",
            "usage_url": f"{settings.SITE_URL}/project/{team.id}/warehouse/usage",
            **get_email_team_and_org_context(organization=organization),
        },
    )
    for user in users:
        message.add_user_recipient(user)
    message.send()


def check_organization_budget(organization_id: str, *, now: datetime | None = None) -> bool:
    """Send the alert for the highest newly reached threshold. Returns whether an alert was claimed."""
    now = now or datetime.now(UTC)
    row = ManagedWarehouseOrgSettings.objects.filter(organization_id=organization_id).first()
    budget = row.monthly_budget_usd if row else None
    if row is None or budget is None or budget <= 0 or not is_console_enabled(organization_id):
        return False
    estimate = estimate_month_to_date_spend(organization_id, now=now)
    threshold = highest_threshold_reached(estimate.total_usd, budget)
    if threshold is None:
        return False
    if not _claim_alert(row.pk, budget, estimate.month_start, threshold):
        return False
    try:
        organization = Organization.objects.get(id=organization_id)
        _send_alert_email(organization, threshold=threshold, budget=budget, estimate=estimate)
    except Exception:
        # The claim stays: a failed send is not retried, so a broken mail path cannot repeat alerts every hour.
        logger.exception(
            "managed_warehouse_budget_alert_send_failed", organization_id=organization_id, threshold=threshold
        )
    return True


def organization_ids_to_check(*, now: datetime | None = None) -> Iterator[str]:
    """Organizations with a budget that have not yet received the top alert this month."""
    month_start = (now or datetime.now(UTC)).date().replace(day=1)
    rows = (
        ManagedWarehouseOrgSettings.objects.filter(monthly_budget_usd__gt=0)
        .exclude(budget_alert_month=month_start, budget_alert_threshold__gte=BUDGET_THRESHOLDS[-1])
        .values_list("organization_id", flat=True)
    )
    for organization_id in rows.iterator():
        yield str(organization_id)
