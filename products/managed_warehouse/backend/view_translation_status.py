from __future__ import annotations

import json
import hashlib
from uuid import UUID

from products.managed_warehouse.backend.models import ManagedWarehouseViewTranslationResult
from products.managed_warehouse.backend.trino_compiler import get_ready_trino_catalog_name

# The control plane provisions an organization's Trino target asynchronously, so a view translation
# job can be created before the target is ready. The error type must stay in
# EXPECTED_CONTROL_FLOW_ERROR_TYPES in posthog/temporal/common/posthog_client.py, or the guard files
# an error tracking issue every time it does its job.
TRINO_TARGET_NOT_READY_ERROR_TYPE = "ManagedWarehouseTrinoTargetNotReady"
TRINO_TARGET_NOT_READY_MESSAGE = "The organization's Trino target is not ready"


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
