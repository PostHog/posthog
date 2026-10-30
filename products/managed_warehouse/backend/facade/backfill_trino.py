"""Register duckling backfill exports in DuckLake through Trino, for warehouses without duckgres."""

from __future__ import annotations

from contextlib import AbstractContextManager

from products.managed_warehouse.backend import backfill_trino
from products.managed_warehouse.backend.facade.contracts import DuckLakeBackfillCatalog

__all__ = ["backfills_through_trino", "connect_backfill_catalog"]


def backfills_through_trino(organization_id: str) -> bool:
    return backfill_trino.backfills_through_trino(organization_id)


def connect_backfill_catalog(organization_id: str) -> AbstractContextManager[DuckLakeBackfillCatalog]:
    return backfill_trino.TrinoBackfillCatalog.connect(organization_id)
