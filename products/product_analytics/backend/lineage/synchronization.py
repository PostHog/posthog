from __future__ import annotations

from typing import TYPE_CHECKING, Literal
from uuid import UUID

from django.db import transaction

import structlog

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception

from products.data_modeling.backend.facade.api import saved_query_ids_by_names
from products.product_analytics.backend.lineage.extraction import extract_saved_query_names, query_fingerprint
from products.product_analytics.backend.models.insight_data_model_dependency import InsightDataModelDependency

if TYPE_CHECKING:
    from products.product_analytics.backend.models.insight import Insight

logger = structlog.get_logger(__name__)


@frozen
class ResolvedInsightDataModelDependencies:
    query_fingerprint: str
    saved_query_ids: frozenset[UUID]


@frozen
class InsightDataModelSynchronizationResult:
    status: Literal["synchronized", "dry_run", "stale", "failed"]
    dependency_count: int


def resolve_insight_data_model_dependencies(*, team_id: int, query: object) -> ResolvedInsightDataModelDependencies:
    fingerprint = query_fingerprint(query)
    table_names = extract_saved_query_names(query)
    saved_query_ids = frozenset(saved_query_ids_by_names(team_id, table_names).values())
    return ResolvedInsightDataModelDependencies(
        query_fingerprint=fingerprint,
        saved_query_ids=saved_query_ids,
    )


def synchronize_insight_data_model_dependencies(
    *,
    team_id: int,
    insight_id: int,
    query_snapshot: object,
    fingerprint: str,
    insight_model: type[Insight],
    apply: bool = True,
) -> InsightDataModelSynchronizationResult:
    try:
        resolved = resolve_insight_data_model_dependencies(team_id=team_id, query=query_snapshot)
        if resolved.query_fingerprint != fingerprint:
            return InsightDataModelSynchronizationResult(status="stale", dependency_count=0)
        if not apply:
            return InsightDataModelSynchronizationResult(
                status="dry_run",
                dependency_count=len(resolved.saved_query_ids),
            )

        with transaction.atomic():
            persisted_query = (
                insight_model.objects_including_soft_deleted.select_for_update()
                .filter(team_id=team_id, id=insight_id)
                .values_list("query", flat=True)
                .first()
            )
            if query_fingerprint(persisted_query) != fingerprint:
                return InsightDataModelSynchronizationResult(status="stale", dependency_count=0)

            dependencies = InsightDataModelDependency.objects.for_team(team_id).filter(insight_id=insight_id)
            dependencies.delete()
            InsightDataModelDependency.objects.for_team(team_id).bulk_create(
                [
                    InsightDataModelDependency(
                        team_id=team_id,
                        insight_id=insight_id,
                        saved_query_id=saved_query_id,
                        query_fingerprint=fingerprint,
                    )
                    for saved_query_id in sorted(resolved.saved_query_ids)
                ]
            )
        return InsightDataModelSynchronizationResult(
            status="synchronized",
            dependency_count=len(resolved.saved_query_ids),
        )
    except Exception as error:
        logger.exception(
            "Failed to synchronize insight data model dependencies",
            team_id=team_id,
            insight_id=insight_id,
            query_fingerprint=fingerprint,
        )
        capture_exception(
            error,
            {
                "team_id": team_id,
                "insight_id": insight_id,
                "query_fingerprint": fingerprint,
            },
        )
        return InsightDataModelSynchronizationResult(status="failed", dependency_count=0)
