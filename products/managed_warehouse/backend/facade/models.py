"""
Model-class wiring for managed_warehouse.

Light re-export of the duckgres server model consumed cross-product. Deliberately free
of heavy imports (no duckdb/psycopg, unlike ``facade.api``), so importing it adds
nothing beyond the models Django already loads at ``django.setup()``.
"""

from products.managed_warehouse.backend.models import DuckgresServer

__all__ = ["DuckgresServer"]
