from collections.abc import Collection, Iterable
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from django.db.models import Q

from products.signals.backend.models import SignalReport
from products.signals.backend.report_content_gates import (
    organization_report_monitoring_enabled,
    team_report_monitoring_enabled,
)

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from products.signals.backend.models import SignalReportCheck


def effective_report_status(status: str, *, team_id: int, monitoring_enabled: bool | None = None) -> str:
    if status != SignalReport.Status.MONITORING:
        return status
    enabled = team_report_monitoring_enabled(team_id) if monitoring_enabled is None else monitoring_enabled
    return status if enabled else SignalReport.Status.RESOLVED


def legacy_agent_checks_enabled(report: SignalReport) -> bool:
    return report.status in {SignalReport.Status.RESOLVED, SignalReport.Status.MONITORING} and not (
        team_report_monitoring_enabled(report.team_id)
    )


def disabled_monitoring_organizations(organization_ids: Iterable[UUID]) -> frozenset[UUID]:
    return frozenset(
        organization_id
        for organization_id in set(organization_ids)
        if not organization_report_monitoring_enabled(organization_id)
    )


def check_monitoring_disabled_organizations(
    checks: "QuerySet[SignalReportCheck]", *, include_resolved: bool = False
) -> frozenset[UUID]:
    statuses = [SignalReport.Status.MONITORING]
    if include_resolved:
        statuses.append(SignalReport.Status.RESOLVED)
    organization_ids = (
        checks.filter(report__status__in=statuses)
        .order_by()
        .values_list("report__team__organization_id", flat=True)
        .distinct()
    )
    return disabled_monitoring_organizations(organization_ids)


def report_status_filter(
    statuses: Collection[str],
    *,
    team_id: int | None = None,
    field: Literal["status", "report__status"] = "status",
    disabled_monitoring_organization_ids: Collection[UUID] | None = None,
) -> Q:
    if field == "status":
        result = Q(status__in=statuses)
        monitoring = Q(status=SignalReport.Status.MONITORING)
    elif field == "report__status":
        result = Q(report__status__in=statuses)
        monitoring = Q(report__status=SignalReport.Status.MONITORING)
    else:
        raise ValueError("Unsupported report status field.")
    if SignalReport.Status.RESOLVED not in statuses:
        return result
    if team_id is not None:
        if not team_report_monitoring_enabled(team_id):
            result |= monitoring
        return result
    if disabled_monitoring_organization_ids is None:
        raise ValueError("Cross-team status filters require a scoped Monitoring gate snapshot.")
    organizations = (
        Q(team__organization_id__in=disabled_monitoring_organization_ids)
        if field == "status"
        else Q(report__team__organization_id__in=disabled_monitoring_organization_ids)
    )
    return result | (monitoring & organizations)
