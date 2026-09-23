from __future__ import annotations

import json
import hashlib
from uuid import UUID

from django.db.models import QuerySet

from products.managed_warehouse.backend.facade.contracts import TrinoCompiledQuery
from products.managed_warehouse.backend.models import ManagedWarehouseViewTranslationResult
from products.managed_warehouse.backend.trino_compiler import get_ready_trino_catalog_name


def source_query_hash(query: object) -> str:
    serialized = json.dumps(query, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(serialized.encode()).hexdigest()


def _current_compiled_translations(
    *,
    organization_id: str | UUID,
    team_id: int,
    saved_query_id: str | UUID,
    source_query: object,
) -> QuerySet[ManagedWarehouseViewTranslationResult]:
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
    )


def get_current_trino_translation(
    *,
    organization_id: str | UUID,
    team_id: int,
    saved_query_id: str | UUID,
    source_query: object,
) -> TrinoCompiledQuery | None:
    result = (
        _current_compiled_translations(
            organization_id=organization_id,
            team_id=team_id,
            saved_query_id=saved_query_id,
            source_query=source_query,
        )
        .order_by("-processed_at", "-created_at", "-id")
        .first()
    )
    if result is None or not result.trino_sql:
        return None
    return TrinoCompiledQuery(sql=result.trino_sql, values=result.trino_values, hogql=result.normalized_hogql)


def is_data_modeling_shadow_ready(
    *,
    organization_id: str | UUID,
    team_id: int,
    saved_query_id: str | UUID,
    source_query: object,
) -> bool:
    if get_ready_trino_catalog_name(str(organization_id)) is None:
        return False
    return _current_compiled_translations(
        organization_id=organization_id,
        team_id=team_id,
        saved_query_id=saved_query_id,
        source_query=source_query,
    ).exists()
