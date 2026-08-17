from __future__ import annotations

from typing import Any

from products.managed_warehouse.backend import source_job_state
from products.managed_warehouse.backend.facade.contracts import ManagedWarehouseSourceJobUpdate

__all__ = [
    "create_duckgres_daily_storage_usage",
    "create_duckgres_daily_usage",
    "record_source_job_state",
]


def record_source_job_state(input: ManagedWarehouseSourceJobUpdate) -> None:
    source_job_state.record_source_job_state(input)


def create_duckgres_daily_usage(**kwargs: Any) -> None:
    """Test seeding for the duckgres compute usage mirror (core tests can't touch the model)."""
    from products.managed_warehouse.backend.models import DuckgresDailyUsage  # noqa: PLC0415

    DuckgresDailyUsage.objects.create(**kwargs)


def create_duckgres_daily_storage_usage(**kwargs: Any) -> None:
    """Test seeding for the duckgres storage usage mirror (core tests can't touch the model)."""
    from products.managed_warehouse.backend.models import DuckgresDailyStorageUsage  # noqa: PLC0415

    DuckgresDailyStorageUsage.objects.create(**kwargs)
