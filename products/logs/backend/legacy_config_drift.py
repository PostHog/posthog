"""The logs rows the legacy config drift report compares with their platform copies."""

from collections.abc import Iterator, Sequence

from products.alerts_platform.backend.facade.contracts import LegacyCopyExpectation, PlatformAlertUpsert
from products.alerts_platform.backend.facade.enums import PlatformAlertOwner
from products.logs.backend.models import LogsAlertConfiguration


def logs_copy_expectations(team_id: int | None, batch_size: int) -> Iterator[Sequence[LegacyCopyExpectation]]:
    rows = LogsAlertConfiguration.objects.filter(owner=PlatformAlertOwner.PLATFORM)
    if team_id is not None:
        rows = rows.filter(team_id=team_id)
    rows = rows.order_by("id")
    batch = list(rows[:batch_size])
    while batch:
        yield [
            LegacyCopyExpectation(
                legacy_configuration_id=alert.id,
                team_id=alert.team_id,
                upsert=_upsert_of(alert),
                # The logs API serves it from the row, so the copy has to carry the same value.
                extra_columns={"first_enabled_at": alert.first_enabled_at},
            )
            for alert in batch
        ]
        batch = list(rows.filter(id__gt=batch[-1].id)[:batch_size])


def _upsert_of(alert: LogsAlertConfiguration) -> PlatformAlertUpsert | None:
    # Off the startup path, because the backfill module loads the platform's write paths.
    from products.logs.backend.platform_alert_backfill import platform_upsert_of  # noqa: PLC0415

    try:
        return platform_upsert_of(alert)
    except TypeError:
        # Filters that are not an object have no platform form.
        return None
