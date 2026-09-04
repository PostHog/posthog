from collections.abc import Collection
from uuid import UUID

from products.product_analytics.backend.facade.contracts import InsightDataModelDependencyDefinition
from products.product_analytics.backend.models.insight_data_model_dependency import InsightDataModelDependency


def _dependency_definitions(
    *, team_id: int, insight_ids: Collection[int] | None = None, saved_query_ids: Collection[str | UUID] | None = None
) -> list[InsightDataModelDependencyDefinition]:
    dependencies = InsightDataModelDependency.objects.for_team(team_id).filter(
        insight__team_id=team_id,
        insight__deleted=False,
    )
    if insight_ids is not None:
        dependencies = dependencies.filter(insight_id__in=insight_ids)
    if saved_query_ids is not None:
        dependencies = dependencies.filter(saved_query_id__in=saved_query_ids)
    rows = dependencies.order_by("insight_id", "saved_query_id").values_list(
        "team_id", "insight_id", "saved_query_id", "query_fingerprint"
    )
    return [
        InsightDataModelDependencyDefinition(
            team_id=row_team_id,
            insight_id=insight_id,
            saved_query_id=saved_query_id,
            query_fingerprint=query_fingerprint,
        )
        for row_team_id, insight_id, saved_query_id, query_fingerprint in rows
    ]


def dependencies_for_insights(
    *, team_id: int, insight_ids: Collection[int]
) -> list[InsightDataModelDependencyDefinition]:
    if not insight_ids:
        return []
    return _dependency_definitions(team_id=team_id, insight_ids=insight_ids)


def dependencies_for_saved_queries(
    *, team_id: int, saved_query_ids: Collection[str | UUID]
) -> list[InsightDataModelDependencyDefinition]:
    if not saved_query_ids:
        return []
    return _dependency_definitions(team_id=team_id, saved_query_ids=saved_query_ids)
