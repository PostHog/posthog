from collections.abc import Collection
from typing import Literal

from django.db.models import Q

from products.signals.backend.models import SignalReport
from products.signals.backend.report_content_gates import (
    organization_report_monitoring_enabled,
    team_report_monitoring_enabled,
)


def effective_report_status(status: str, *, team_id: int, monitoring_enabled: bool | None = None) -> str:
    if status != SignalReport.Status.MONITORING:
        return status
    enabled = team_report_monitoring_enabled(team_id) if monitoring_enabled is None else monitoring_enabled
    return status if enabled else SignalReport.Status.RESOLVED


def report_status_filter(
    statuses: Collection[str], *, team_id: int | None = None, field: Literal["status", "report__status"] = "status"
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
    monitoring_organizations = (
        SignalReport.objects.filter(status=SignalReport.Status.MONITORING)
        .values_list("team__organization_id", flat=True)
        .distinct()
    )
    disabled = [
        organization_id
        for organization_id in monitoring_organizations
        if not organization_report_monitoring_enabled(organization_id)
    ]
    organizations = (
        Q(team__organization_id__in=disabled) if field == "status" else Q(report__team__organization_id__in=disabled)
    )
    return result | (monitoring & organizations)
