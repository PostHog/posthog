"""Warehouse alert destination vocabulary for the warehouse presentation endpoints."""

from products.warehouse_sources.backend.sync_alerts.destinations import (
    WAREHOUSE_ALERT_DESTINATION_TYPES,
    WAREHOUSE_DESTINATION_EVENT_KINDS,
)

__all__ = ["WAREHOUSE_DESTINATION_EVENT_KINDS", "WAREHOUSE_ALERT_DESTINATION_TYPES"]
