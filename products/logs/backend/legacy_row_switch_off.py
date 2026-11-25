from collections.abc import Sequence
from uuid import UUID

from products.alerts_platform.backend.facade.enums import PlatformAlertOwner
from products.logs.backend.models import LogsAlertConfiguration


def switch_off_rows(team_id: int, legacy_ids: Sequence[UUID], apply: bool) -> int:
    # A row whose own owner is not the platform stays as it is even when a copy says the platform owns
    # it, because readers show such an alert from its row.
    rows = LogsAlertConfiguration.objects.filter(
        team_id=team_id, id__in=legacy_ids, owner=PlatformAlertOwner.PLATFORM, enabled=True
    )
    # A queryset update, not `save()` or the state machine: saving fires the activity log signal, which
    # would show every customer an alert disable they did not make, and the copy holds the state.
    # nosemgrep: logs-alert-state-direct-mutation (the platform copy holds this alert's state)
    return rows.update(enabled=False) if apply else rows.count()
