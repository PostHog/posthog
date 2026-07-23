from django.db import migrations
from django.db.models import Q, TextField
from django.db.models.functions import Cast

BATCH_SIZE = 1_000

# Query kinds removed together with the Revenue analytics dashboard. Any saved insight still
# pointing at one of these has a query the schema can no longer parse, so it renders broken.
# Soft-delete those insights and any dashboard tiles that embed them, so they drop out of
# every list and dashboard without touching unrelated insights.
REMOVED_REVENUE_QUERY_KINDS = [
    "RevenueAnalyticsGrossRevenueQuery",
    "RevenueAnalyticsMetricsQuery",
    "RevenueAnalyticsMRRQuery",
    "RevenueAnalyticsOverviewQuery",
    "RevenueAnalyticsTopCustomersQuery",
    "RevenueExampleEventsQuery",
    "RevenueExampleDataWarehouseTablesQuery",
]


def soft_delete_revenue_insights(apps, schema_editor):
    Insight = apps.get_model("product_analytics", "Insight")
    DashboardTile = apps.get_model("dashboards", "DashboardTile")

    # The removed kinds are unique markers, so a substring match on the serialized query
    # catches every nesting (bare, InsightVizNode.source, DataTableNode.source) without
    # false positives.
    kind_filter = Q()
    for kind in REMOVED_REVENUE_QUERY_KINDS:
        kind_filter |= Q(query_text__icontains=kind)

    revenue_insight_ids = (
        Insight.objects.annotate(query_text=Cast("query", TextField())).filter(kind_filter).values("pk")
    )

    # Detach these insights from dashboards first, so no tile is left pointing at a
    # soft-deleted insight. Covers already-deleted insights too, in case a prior run
    # deleted the insight but not its tiles.
    while True:
        tile_ids = list(
            DashboardTile.objects.filter(insight_id__in=revenue_insight_ids)
            .exclude(deleted=True)
            .values_list("id", flat=True)[:BATCH_SIZE]
        )
        if not tile_ids:
            break

        DashboardTile.objects.filter(id__in=tile_ids).update(deleted=True)

    while True:
        ids = list(
            Insight.objects.annotate(query_text=Cast("query", TextField()))
            .filter(deleted=False)
            .filter(kind_filter)
            .values_list("id", flat=True)[:BATCH_SIZE]
        )
        if not ids:
            break

        Insight.objects.filter(id__in=ids).update(deleted=True)


class Migration(migrations.Migration):
    # Batches commit independently so a large backfill doesn't run in one long transaction.
    atomic = False

    dependencies = [
        ("product_analytics", "0003_drop_insightcachingstate_table"),
        ("dashboards", "0014_backfill_dashboardtemplate_button_tile_type"),
    ]

    operations = [
        migrations.RunPython(soft_delete_revenue_insights, migrations.RunPython.noop),
    ]
