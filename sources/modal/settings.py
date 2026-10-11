from datetime import timedelta
from typing import Literal

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field


@frozen
class BillingTable:
    resolution: Literal["d", "h"]
    default_lookback: timedelta
    window_size: timedelta
    # Modal's billing docs say report data usually lands within minutes, but collection delays
    # can occur. `modal_source` already re-reads the watermark's own interval every sync to pick
    # up its latest cost, but that only covers the single most recent interval. This shifts the
    # watermark used for the source query back further, so each incremental run re-reads a
    # trailing overlap window and also catches a delayed interval older than the last one synced.
    # Merge dedupes the re-read rows on the primary key.
    default_incremental_lookback: timedelta


ENDPOINTS = {
    "billing_report_daily": BillingTable(
        resolution="d",
        default_lookback=timedelta(days=365),
        window_size=timedelta(days=30),
        default_incremental_lookback=timedelta(days=3),
    ),
    "billing_report_hourly": BillingTable(
        resolution="h",
        default_lookback=timedelta(days=30),
        window_size=timedelta(days=2),
        default_incremental_lookback=timedelta(hours=6),
    ),
}
INCREMENTAL_FIELDS = {name: [incremental_field("interval_start")] for name in ENDPOINTS}
DEFAULT_INCREMENTAL_LOOKBACK_SECONDS = {
    name: int(table.default_incremental_lookback.total_seconds()) for name, table in ENDPOINTS.items()
}
PRIMARY_KEYS = ["object_id", "interval_start", "environment_name"]
PARTITION_KEY = "interval_start"
