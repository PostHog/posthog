from collections.abc import Collection

from django.db import connections, router
from django.db.models import Q, QuerySet
from django.utils.timezone import now

from products.product_analytics.backend.facade.contracts import INSIGHT_VIEW_CONTEXT_WRITE_INTERVAL
from products.product_analytics.backend.models.insight import Insight, InsightViewed


def record_insight_view_context(
    *, team_id: int, insight_ids: Collection[int], user_id: int | None, source: str, dashboard_id: int | None = None
) -> None:
    if not source:
        raise ValueError("Context access requires an attributed source")
    insights = Insight.objects.filter(team_id=team_id, pk__in=insight_ids, deleted=False)
    if dashboard_id is not None:
        insights = insights.filter(
            Q(dashboard_tiles__deleted=False) | Q(dashboard_tiles__deleted__isnull=True),
            Q(dashboard_tiles__dashboard__deleted=False) | Q(dashboard_tiles__dashboard__deleted__isnull=True),
            dashboard_tiles__dashboard_id=dashboard_id,
            dashboard_tiles__dashboard__team_id=team_id,
        )
    ids = list(insights.order_by("pk").values_list("pk", flat=True).distinct())
    if not ids:
        return
    requested_at = now()
    connection = connections[router.db_for_write(InsightViewed)]
    table = connection.ops.quote_name(InsightViewed._meta.db_table)
    conflict = "(COALESCE(team_id, 0), COALESCE(user_id, 0), insight_id, source, COALESCE(dashboard_id, 0))"
    row_team_id = None if source == "shared" and user_id is None else team_id
    placeholders = ", ".join(["(%s, %s, %s, %s, %s, %s)"] * len(ids))
    params = [
        value for insight_id in ids for value in (row_team_id, insight_id, user_id, source, dashboard_id, requested_at)
    ]
    with connection.cursor() as cursor:
        cursor.execute(
            f"""INSERT INTO {table} (team_id, insight_id, user_id, source, dashboard_id, last_viewed_at)
                VALUES {placeholders}
                ON CONFLICT {conflict} DO UPDATE SET last_viewed_at = EXCLUDED.last_viewed_at
                WHERE {table}.last_viewed_at < %s""",
            [*params, requested_at - INSIGHT_VIEW_CONTEXT_WRITE_INTERVAL],
        )


def insight_view_contexts(*, team_id: int, insight_ids: Collection[int]) -> QuerySet[InsightViewed]:
    return InsightViewed.objects.filter(
        Q(team_id=team_id) | Q(team_id__isnull=True), insight_id__in=insight_ids, insight__team_id=team_id
    )
