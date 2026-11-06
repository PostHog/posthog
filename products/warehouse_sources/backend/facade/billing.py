"""Billing-facing exports for warehouse_sources.

The usage reporter (posthog/tasks/usage_report.py) lives in the ``posthog`` module,
which may only import ``products.warehouse_sources`` through the facade (see tach.toml).
"""

from products.warehouse_sources.backend.billing import get_free_historical_rows_synced_by_team, get_rows_synced_by_team

__all__ = [
    "get_free_historical_rows_synced_by_team",
    "get_rows_synced_by_team",
]
