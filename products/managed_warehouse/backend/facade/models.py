"""
Model-class wiring for managed_warehouse.

Light re-export of the duckgres model classes consumed cross-product — Django admin,
the data-ops status reads, and the sink's schema-state bookkeeping. Deliberately free
of heavy imports (no duckdb/psycopg, unlike ``facade.api``), so importing it adds
nothing beyond the models Django already loads at ``django.setup()``.
"""

from products.managed_warehouse.backend.models import DuckgresServer, DuckgresSinkSchemaState

__all__ = ["DuckgresServer", "DuckgresSinkSchemaState"]
