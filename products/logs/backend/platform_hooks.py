"""The logs hooks the alerts platform calls, registered from `ready()`.

Each hook imports the logs models on its first call, because `ready()` runs in every process.
"""

from uuid import UUID


def logs_alert_creator(*, team_id: int, alert_id: UUID) -> int | None:
    from products.logs.backend.models import LogsAlertConfiguration  # noqa: PLC0415 - keeps models off the startup path

    return (
        LogsAlertConfiguration.objects.filter(team_id=team_id, id=alert_id)
        .values_list("created_by_id", flat=True)
        .first()
    )
