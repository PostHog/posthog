"""Billing-facing exports for warehouse_sources.

The usage reporter (posthog/tasks/usage_report.py) lives in the ``posthog`` module,
which may only import ``products.warehouse_sources`` through the facade (hoglint's ``public-surface``).
"""

from products.warehouse_sources.backend.billing import (
    get_destination_bytes_exported_by_team,
    get_free_historical_rows_synced_by_team,
    get_rows_synced_by_team,
)

__all__ = [
    "get_destination_bytes_exported_by_team",
    "get_free_historical_rows_synced_by_team",
    "get_rows_synced_by_team",
]
