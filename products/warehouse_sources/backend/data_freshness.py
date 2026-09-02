from datetime import datetime

from django.db.models import Max

from posthog.data_freshness import POSTGRES_TIMEOUT_MS, DataSourceSpec, ProbeWindow
from posthog.models.utils import execute_with_timeout
from posthog.schema_enums import ProductKey

from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema


def last_sync_at(team_ids: list[int], window: ProbeWindow) -> dict[int, datetime]:
    """Read the per-schema sync stamp rather than aggregating job history.

    `ExternalDataJob` is one row per schema per run and has no index serving a `finished_at`
    range, so a windowed max over it reads a team's whole history. `ExternalDataSchema` holds
    one row per schema off the team FK, and is what the rest of the codebase treats as "last
    successful sync".
    """
    rows = (
        ExternalDataSchema.objects.filter(
            team_id__in=team_ids,
            last_synced_at__gte=window.cutoff,
            last_synced_at__lte=window.horizon,
        )
        .values("team_id")
        .annotate(last_synced=Max("last_synced_at"))
    )
    with execute_with_timeout(POSTGRES_TIMEOUT_MS):
        return {row["team_id"]: row["last_synced"] for row in rows}


DATA_SOURCES = [DataSourceSpec(product=ProductKey.DATA_WAREHOUSE, probe=last_sync_at)]
