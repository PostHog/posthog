"""Model-class wiring for managed_warehouse.

Light re-exports of the managed_warehouse models' public surface — the ORM model
classes — for cross-product consumers that genuinely need them (the billing usage
report reads the duckgres usage mirror). Deliberately free of heavy imports, so
importing it adds nothing beyond the models Django already loads at
``django.setup()``.

Consumers that only read fields should use ``facade.api`` instead.
"""

from products.managed_warehouse.backend.models import DuckgresDailyStorageUsage, DuckgresDailyUsage, DuckgresUsageCursor

__all__ = [
    "DuckgresDailyStorageUsage",
    "DuckgresDailyUsage",
    "DuckgresUsageCursor",
]
