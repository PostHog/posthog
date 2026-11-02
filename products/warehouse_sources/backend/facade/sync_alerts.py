"""Warehouse alert destination vocabulary for the warehouse presentation endpoints."""

from products.warehouse_sources.backend.sync_alerts.destinations import (
    EVENT_IDS,
    EVENT_KIND_CONFIG,
    WAREHOUSE_ALERT_DESTINATION_TYPES,
)

__all__ = ["EVENT_IDS", "EVENT_KIND_CONFIG", "WAREHOUSE_ALERT_DESTINATION_TYPES"]
