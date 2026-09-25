from collections.abc import Collection
from datetime import datetime, timedelta

from django.db import connections, router
from django.db.models import Q
from django.utils.timezone import now

from products.product_analytics.backend.models.insight import Insight
from products.product_analytics.backend.models.insight_query_demand import InsightQueryDemand

DEMAND_WRITE_INTERVAL = timedelta(minutes=1)
DEMAND_RETENTION = timedelta(days=30)


def record_insight_query_demand(*, team_id: int, insight_ids: Collection[int], dashboard_id: int | None = None) -> None:
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
    connection = connections[router.db_for_write(InsightQueryDemand)]
    table = connection.ops.quote_name(InsightQueryDemand._meta.db_table)
    # Django bulk upserts cannot target the partial unique indexes for these two contexts.
    conflict = "(team_id, insight_id) WHERE dashboard_id IS NULL"
    if dashboard_id is not None:
        conflict = "(team_id, insight_id, dashboard_id) WHERE dashboard_id IS NOT NULL"
    placeholders = ", ".join(["(%s, %s, %s, %s)"] * len(ids))
    params = [value for insight_id in ids for value in (team_id, insight_id, dashboard_id, requested_at)]
    with connection.cursor() as cursor:
        cursor.execute(
            f"""INSERT INTO {table} (team_id, insight_id, dashboard_id, last_requested_at)
                VALUES {placeholders}
                ON CONFLICT {conflict} DO UPDATE SET last_requested_at = EXCLUDED.last_requested_at
                WHERE {table}.last_requested_at < EXCLUDED.last_requested_at - %s""",
            [*params, DEMAND_WRITE_INTERVAL],
        )


def standalone_insights_with_recent_demand(
    *, team_id: int, insight_ids: Collection[int], threshold: datetime
) -> set[int]:
    return set(
        InsightQueryDemand.objects.filter(
            team_id=team_id,
            insight_id__in=insight_ids,
            dashboard_id__isnull=True,
            last_requested_at__gte=threshold - DEMAND_WRITE_INTERVAL,
        ).values_list("insight_id", flat=True)
    )


def prune_insight_query_demand(*, team_id: int) -> None:
    expired = list(
        InsightQueryDemand.objects.filter(team_id=team_id, last_requested_at__lt=now() - DEMAND_RETENTION)
        .order_by("last_requested_at")
        .values_list("pk", flat=True)[:1000]
    )
    InsightQueryDemand.objects.filter(
        team_id=team_id, pk__in=expired, last_requested_at__lt=now() - DEMAND_RETENTION
    ).delete()
