from django.db import migrations

BATCH_SIZE = 1_000
METRICS_QUERY_KINDS = ["MetricsQuery", "MetricsHistogramQuery"]


def _selections(values: dict) -> dict:
    return {
        name: {"values": list(value.get("values") or []), **({"all": True} if value.get("all") else {})}
        for name, value in values.items()
        if isinstance(value, dict)
    }


def remove_metrics_variable_values(apps, schema_editor):
    Insight = apps.get_model("product_analytics", "Insight")
    AlertConfiguration = apps.get_model("alerts", "AlertConfiguration")
    db_alias = schema_editor.connection.alias

    # The query column has no index for this filter, so scan the table once and batch over the ids.
    insight_ids = list(
        Insight.objects.using(db_alias)
        .filter(query__kind__in=METRICS_QUERY_KINDS, query__has_key="variables")
        .values_list("id", flat=True)
    )

    for start in range(0, len(insight_ids), BATCH_SIZE):
        insights = list(
            Insight.objects.using(db_alias).filter(id__in=insight_ids[start : start + BATCH_SIZE]).only("id", "query")
        )
        values_by_insight = {}
        for insight in insights:
            values = insight.query.pop("variables", None)
            if isinstance(values, dict) and values:
                values_by_insight[insight.id] = _selections(values)

        # Alerts on these insights ran with the insight's values, so each one keeps a copy.
        alerts = []
        for alert in (
            AlertConfiguration.objects.using(db_alias)
            .filter(insight_id__in=values_by_insight.keys())
            .only("id", "insight_id", "config")
        ):
            config = alert.config or {}
            if config.get("type") == "MetricsAlertConfig" and not config.get("variables"):
                alert.config = {**config, "variables": values_by_insight[alert.insight_id]}
                alerts.append(alert)
        AlertConfiguration.objects.using(db_alias).bulk_update(alerts, ["config"])
        Insight.objects.using(db_alias).bulk_update(insights, ["query"])


class Migration(migrations.Migration):
    dependencies = [
        ("product_analytics", "0011_insight_viewed_context_fields"),
        ("alerts", "0016_insight_alert_investigation_age_index"),
    ]

    operations = [
        migrations.RunPython(remove_metrics_variable_values, migrations.RunPython.noop),
    ]
