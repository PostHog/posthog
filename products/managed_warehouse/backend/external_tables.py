from __future__ import annotations

from uuid import UUID

from products.managed_warehouse.backend.common import duckgres_data_imports_schema
from products.managed_warehouse.backend.models import ManagedWarehouseExternalTable
from products.warehouse_sources.backend.facade.external_delta import get_external_delta_table


def enroll_external_table(team_id: int, table_id: UUID) -> ManagedWarehouseExternalTable:
    source = get_external_delta_table(team_id, table_id)
    registration, _ = ManagedWarehouseExternalTable.objects.for_team(team_id).get_or_create(
        table_id=table_id,
        defaults={
            "team_id": team_id,
            "source_fingerprint": source.fingerprint,
            "warehouse_schema": duckgres_data_imports_schema(team_id),
            "warehouse_table": f"external_{table_id.hex}",
        },
    )
    if registration.source_fingerprint != source.fingerprint:
        raise ValueError("The enrolled table location changed; enroll a new warehouse table")
    return registration
