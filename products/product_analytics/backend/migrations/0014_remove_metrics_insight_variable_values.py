from django.db import migrations

BATCH_SIZE = 1_000
METRICS_QUERY_KINDS = ["MetricsQuery", "MetricsHistogramQuery"]


def _selection(value: dict) -> dict | None:
    """The alert form of a stored value, or None when an alert cannot hold the same selection.

    An alert selection holds only `values` and `all`. All with an `allValue` puts that text in PromQL,
    and All with a `definition` loads its SQL options from it. An alert has neither, so it would run a different query.
    """
    if value.get("all") and (value.get("allValue") or value.get("definition")):
        return None
    return {"values": list(value.get("values") or []), **({"all": True} if value.get("all") else {})}


def _alert_needs_values(alert) -> bool:
    config = alert.config or {}
    return config.get("type") == "MetricsAlertConfig" and not config.get("variables")


def remove_metrics_variable_values(apps, schema_editor):
    Insight = apps.get_model("product_analytics", "Insight")
    AlertConfiguration = apps.get_model("alerts", "AlertConfiguration")
    db_alias = schema_editor.connection.alias

    # The query column has no index for this filter, so scan the table once and batch over the ids.
    insight_ids = sorted(
        Insight.objects.using(db_alias)
        .filter(query__kind__in=METRICS_QUERY_KINDS, query__has_key="variables")
        .values_list("id", flat=True)
    )

    for start in range(0, len(insight_ids), BATCH_SIZE):
        # Alert saves and checks lock the insight before its alerts, so this migration locks them in that order too.
        insights = list(
            Insight.objects.using(db_alias)
            .select_for_update(no_key=True)
            .filter(id__in=insight_ids[start : start + BATCH_SIZE])
            .order_by("id")
            .only("id", "query")
        )
        alerts_by_insight: dict[int, list] = {}
        for alert in (
            AlertConfiguration.objects.using(db_alias)
            .select_for_update(no_key=True)
            .filter(insight_id__in=[insight.id for insight in insights])
            .order_by("id")
            .only("id", "insight_id", "config")
        ):
            if _alert_needs_values(alert):
                alerts_by_insight.setdefault(alert.insight_id, []).append(alert)

        changed_insights = []
        changed_alerts = []
        for insight in insights:
            values = insight.query.get("variables")
            alerts = alerts_by_insight.get(insight.id, [])
            if isinstance(values, dict) and values and alerts:
                selections = {name: _selection(value) for name, value in values.items() if isinstance(value, dict)}
                # Alerts on this insight ran with its values. Keep the values on the insight when an alert cannot copy them.
                if any(selection is None for selection in selections.values()):
                    continue
                for alert in alerts:
                    alert.config = {**alert.config, "variables": selections}
                    changed_alerts.append(alert)
            insight.query.pop("variables", None)
            changed_insights.append(insight)

        AlertConfiguration.objects.using(db_alias).bulk_update(changed_alerts, ["config"])
        Insight.objects.using(db_alias).bulk_update(changed_insights, ["query"])


class Migration(migrations.Migration):
    dependencies = [
        ("product_analytics", "0013_squash_2026_11_02_schema_addons"),
        ("alerts", "0017_squash_2026_11_02_finalize_fks"),
    ]

    operations = [
        migrations.RunPython(remove_metrics_variable_values, migrations.RunPython.noop),
    ]
