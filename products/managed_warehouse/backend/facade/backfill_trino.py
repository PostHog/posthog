"""Register duckling backfill exports in DuckLake or hoglake through Trino instead of duckgres."""

from __future__ import annotations

from contextlib import AbstractContextManager

from products.managed_warehouse.backend import backfill_trino
from products.managed_warehouse.backend.facade.contracts import (
    DuckLakeBackfillCatalog,
    HoglakeBackfillCatalog,
    TrinoBackend,
)

__all__ = [
    "backfills_through_hoglake",
    "backfills_through_trino",
    "connect_backfill_catalog",
    "connect_hoglake_backfill_catalog",
    "get_cached_trino_backend",
    "get_trino_backend",
]


def backfills_through_trino(organization_id: str) -> bool:
    return backfill_trino.backfills_through_trino(organization_id)


def backfills_through_hoglake(organization_id: str) -> bool:
    return backfill_trino.backfills_through_hoglake(organization_id)


def get_trino_backend(organization_id: str, *, use_cache: bool = False) -> TrinoBackend:
    return backfill_trino.trino_backend_for(organization_id, use_cache=use_cache)


def get_cached_trino_backend(organization_id: str) -> TrinoBackend | None:
    return backfill_trino.cached_trino_backend(organization_id)


def connect_backfill_catalog(
    organization_id: str, *, canary: bool = False, team_id: int | None = None
) -> AbstractContextManager[DuckLakeBackfillCatalog]:
    return backfill_trino.TrinoBackfillCatalog.connect(organization_id, canary=canary, team_id=team_id)


def connect_hoglake_backfill_catalog(
    organization_id: str, *, canary: bool = False, team_id: int
) -> AbstractContextManager[HoglakeBackfillCatalog]:
    return backfill_trino.HoglakeBackfillCatalog.connect(organization_id, canary=canary, team_id=team_id)
