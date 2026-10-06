from datetime import timedelta
from typing import Literal

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field


@frozen
class BillingTable:
    resolution: Literal["d", "h"]
    default_lookback: timedelta
    window_size: timedelta


ENDPOINTS = {
    "billing_report_daily": BillingTable(
        resolution="d", default_lookback=timedelta(days=365), window_size=timedelta(days=30)
    ),
    "billing_report_hourly": BillingTable(
        resolution="h", default_lookback=timedelta(days=30), window_size=timedelta(days=2)
    ),
}
INCREMENTAL_FIELDS = {name: [incremental_field("interval_start")] for name in ENDPOINTS}
PRIMARY_KEYS = ["object_id", "interval_start", "environment_name"]
PARTITION_KEY = "interval_start"
