"""The logs alerts whose destinations the cutover bucket report reads."""

from __future__ import annotations

from collections.abc import Iterator

from products.logs.backend.models import LogsAlertConfiguration


def enabled_logs_alerts(*, team_id: int | None = None) -> Iterator[tuple[int, str]]:
    alerts = LogsAlertConfiguration.objects.filter(enabled=True).order_by("team_id", "created_at")
    if team_id is not None:
        alerts = alerts.filter(team_id=team_id)
    for alert_team_id, alert_id in alerts.values_list("team_id", "id").iterator():
        yield alert_team_id, str(alert_id)
