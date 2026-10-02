from datetime import datetime

from posthog.data_freshness import DataSourceSpec, ProbeWindow, latest_per_team
from posthog.schema_enums import ProductKey

from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema


def last_sync_at(team_ids: list[int], window: ProbeWindow) -> dict[int, datetime]:
    """Read the per-schema sync stamp rather than aggregating job history.

    `ExternalDataJob` is one row per schema per run and has no index serving a `finished_at`
    range, so a windowed max over it reads a team's whole history. `ExternalDataSchema` holds
    one row per schema off the team FK, and is what the rest of the codebase treats as "last
    successful sync".
    """
    return latest_per_team(ExternalDataSchema.objects.all(), "last_synced_at", team_ids, window)


DATA_SOURCES = [DataSourceSpec(product=ProductKey.DATA_WAREHOUSE, probe=last_sync_at)]
