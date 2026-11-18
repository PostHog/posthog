"""The logs rows the legacy config drift report compares with their platform copies."""

from collections.abc import Sequence
from uuid import UUID

from products.alerts_platform.backend.facade.contracts import LegacyCopyExpectation
from products.alerts_platform.backend.facade.enums import PlatformAlertOwner
from products.logs.backend.models import LogsAlertConfiguration


def logs_copy_expectations(team_id: int | None, after: UUID | None, limit: int) -> Sequence[LegacyCopyExpectation]:
    # Off the startup path, because the backfill module loads the platform's write paths.
    from products.logs.backend.platform_alert_backfill import platform_upsert_of  # noqa: PLC0415

    rows = LogsAlertConfiguration.objects.filter(owner=PlatformAlertOwner.PLATFORM)
    if team_id is not None:
        rows = rows.filter(team_id=team_id)
    if after is not None:
        rows = rows.filter(id__gt=after)
    expectations = []
    for alert in rows.order_by("id")[:limit]:
        try:
            upsert = platform_upsert_of(alert)
        except TypeError:
            upsert = None
        expectations.append(
            LegacyCopyExpectation(
                legacy_configuration_id=alert.id,
                team_id=alert.team_id,
                upsert=upsert,
                # The logs API serves it from the row, so the copy has to carry the same value.
                extra_columns={"first_enabled_at": alert.first_enabled_at},
            )
        )
    return expectations
