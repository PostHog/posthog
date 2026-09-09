from __future__ import annotations

import json
import hashlib
from uuid import UUID

from products.managed_warehouse.backend.models import ManagedWarehouseViewTranslationResult
from products.managed_warehouse.backend.trino_compiler import get_ready_trino_catalog_name


def source_query_hash(query: object) -> str:
    serialized = json.dumps(query, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(serialized.encode()).hexdigest()


def is_data_modeling_shadow_ready(
    *,
    organization_id: str | UUID,
    team_id: int,
    saved_query_id: str | UUID,
    source_query: object,
) -> bool:
    if get_ready_trino_catalog_name(str(organization_id)) is None:
        return False

    return (
        ManagedWarehouseViewTranslationResult.objects.for_team(team_id)
        .filter(
            job__organization_id=organization_id,
            saved_query_id=saved_query_id,
            source_query_hash=source_query_hash(source_query),
            status=ManagedWarehouseViewTranslationResult.Status.COMPILED,
        )
        .exclude(trino_sql__isnull=True)
        .exclude(trino_sql="")
        .exists()
    )
