from dataclasses import dataclass

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    PartitionFormat,
    PartitionMode,
)


@dataclass
class ImaggaEndpointConfig:
    name: str
    # Fields the rows are merged on. Imagga's /usage endpoint has no record ids, so the keys are
    # derived from the shape we normalize to (the billing period for the snapshot, the day for the
    # per-day series). Both endpoints are full-refresh only, so these keys mainly document intent.
    primary_keys: list[str]
    partition_keys: list[str] | None = None
    partition_mode: PartitionMode | None = None
    partition_format: PartitionFormat | None = None
    should_sync_default: bool = True
    description: str | None = None


# Imagga is an on-demand image-inference API (tagging, categorization, cropping, faces, OCR, content
# moderation), not a record-oriented dataset provider — there are no list/export endpoints that emit
# rows for a warehouse. The only pollable account data is GET /usage, which returns the current
# billing-period consumption plus a per-day usage histogram. We surface that single response as two
# tables: a flat snapshot and the exploded daily series. Neither exposes a server-side timestamp
# filter, so both are full refresh only (no incremental sync, no pagination, no cursors).
IMAGGA_ENDPOINTS: dict[str, ImaggaEndpointConfig] = {
    "usage": ImaggaEndpointConfig(
        name="usage",
        primary_keys=["billing_period_start"],
        description="Current billing-period consumption snapshot: request and processed counters, the monthly request limit, and concurrency (current vs max). One row, full refresh.",
    ),
    "daily_usage": ImaggaEndpointConfig(
        name="daily_usage",
        primary_keys=["date"],
        # `date` is a calendar day derived from the usage histogram — historical days never move, so
        # it's a stable partition key.
        partition_keys=["date"],
        partition_mode="datetime",
        partition_format="month",
        description="Per-day request counts from the account's usage history, one row per day ({date, timestamp, count}). Full refresh.",
    ),
}

ENDPOINTS = tuple(IMAGGA_ENDPOINTS.keys())
