"""Warehouse alert destination vocabulary for the warehouse presentation endpoints."""

from products.warehouse_sources.backend.sync_alerts.destinations import (
    DESTINATION_EVENT_KINDS,
    WAREHOUSE_ALERT_DESTINATION_TYPES,
)

__all__ = ["DESTINATION_EVENT_KINDS", "WAREHOUSE_ALERT_DESTINATION_TYPES"]
