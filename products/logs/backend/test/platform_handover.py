from datetime import datetime

from django.db import transaction

from products.alerts_platform.backend.facade.enums import PlatformAlertOwner
from products.logs.backend.models import LogsAlertConfiguration
from products.logs.backend.platform_ownership import hand_over


def hand_over_team(team_id: int, now: datetime) -> None:
    for alert_id in (
        LogsAlertConfiguration.objects.filter(team_id=team_id)
        .exclude(owner=PlatformAlertOwner.PLATFORM)
        .values_list("id", flat=True)
    ):
        with transaction.atomic():
            assert hand_over(LogsAlertConfiguration.objects.select_for_update().get(id=alert_id), now)
