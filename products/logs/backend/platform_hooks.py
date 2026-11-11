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


def logs_alert_viewer(*, team_id: int, alert_id: UUID, user_id: int) -> bool:
    from posthog.models import User  # noqa: PLC0415 - keeps models off the startup path

    from products.access_control.backend.facade.user_access_control import UserAccessControl  # noqa: PLC0415
    from products.logs.backend.models import LogsAlertConfiguration  # noqa: PLC0415

    alert = LogsAlertConfiguration.objects.filter(team_id=team_id, id=alert_id).select_related("team").first()
    user = User.objects.filter(id=user_id).first() if alert is not None else None
    if alert is None or user is None:
        return False
    # Logs alerts take their access from the logs product as a whole, as the logs alert API does.
    return UserAccessControl(user, team=alert.team).check_access_level_for_resource("logs", "viewer")
