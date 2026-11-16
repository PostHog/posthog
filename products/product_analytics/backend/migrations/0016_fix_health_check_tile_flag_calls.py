from django.db import migrations
from django.utils import timezone

BATCH_SIZE = 1_000

# The original query of the "Built-in events health check" tile in the global "My PostHog Billable Usage"
# dashboard template. Its single scan of events never reads $feature_flag_called from flag_evaluations, so on
# flag evaluations mode 2 the tile reports flag calls as not arriving.
OLD_QUERY = """-- Every PostHog built-in event arriving in the selected date range, plus a core
-- set we always check so a silently dropped one still shows at zero.
-- Built-in events are PostHog's own ($-prefixed) events plus the survey events.
-- If a CORE event shows 'Not arriving', check your SDK config and any before_send
-- or event allowlist: those silently drop internals like $pageleave (bounce rate),
-- $feature_flag_called, $web_vitals, and $exception.
-- The date range comes from the dashboard's date picker (defaults to last 30 days).
WITH arriving AS (
    -- volume of every built-in event actually captured in the window
    SELECT
        event   AS event_name,
        count() AS events_in_period
    FROM events
    WHERE timestamp >= {filters.dateRange.from}
      AND timestamp < {filters.dateRange.to}
      AND (startsWith(event, '$') OR event IN ('survey shown', 'survey sent', 'survey dismissed'))
    GROUP BY event_name
),
core AS (
    -- core built-ins worth flagging even when absent (a missing one usually
    -- means an SDK misconfig or a before_send filter dropping it)
    SELECT arrayJoin([
        '$pageview', '$pageleave', '$autocapture', '$identify',
        '$feature_flag_called', '$web_vitals', '$exception',
        'survey shown', 'survey sent'
    ]) AS event_name
),
all_built_in AS (
    -- everything arriving, plus any core event that did not arrive
    SELECT event_name FROM arriving
    UNION DISTINCT
    SELECT event_name FROM core
)
SELECT
    all_built_in.event_name                AS built_in_event,
    coalesce(arriving.events_in_period, 0)  AS events_in_period,
    if(coalesce(arriving.events_in_period, 0) = 0,
       'Not arriving (unused, or filtered out?)',
       'OK')                                AS status
FROM all_built_in
LEFT JOIN arriving ON all_built_in.event_name = arriving.event_name
ORDER BY if(events_in_period = 0, 0, 1) ASC, events_in_period DESC
LIMIT 200"""

# The query that replaced it in the template. It counts $feature_flag_called in its own scan, which PostHog reads
# from flag_evaluations on mode 2.
NEW_QUERY = """-- Every PostHog built-in event arriving in the selected date range, plus a core
-- set we always check so a silently dropped one still shows at zero.
-- Built-in events are PostHog's own ($-prefixed) events plus the survey events.
-- If a CORE event shows 'Not arriving', check your SDK config and any before_send
-- or event allowlist: those silently drop internals like $pageleave (bounce rate),
-- $feature_flag_called, $web_vitals, and $exception.
-- The date range comes from the dashboard's date picker (defaults to last 30 days).
WITH arriving AS (
    -- volume of every built-in event actually captured in the window
    SELECT
        event   AS event_name,
        count() AS events_in_period
    FROM events
    WHERE timestamp >= {filters.dateRange.from}
      AND timestamp < {filters.dateRange.to}
      AND (startsWith(event, '$') OR event IN ('survey shown', 'survey sent', 'survey dismissed'))
      AND event != '$feature_flag_called'
    GROUP BY event_name
    UNION ALL
    -- $feature_flag_called gets its own scan so PostHog can read it from wherever flag calls are stored
    SELECT
        '$feature_flag_called' AS event_name,
        count()                AS events_in_period
    FROM events
    WHERE timestamp >= {filters.dateRange.from}
      AND timestamp < {filters.dateRange.to}
      AND event = '$feature_flag_called'
),
core AS (
    -- core built-ins worth flagging even when absent (a missing one usually
    -- means an SDK misconfig or a before_send filter dropping it)
    SELECT arrayJoin([
        '$pageview', '$pageleave', '$autocapture', '$identify',
        '$feature_flag_called', '$web_vitals', '$exception',
        'survey shown', 'survey sent'
    ]) AS event_name
),
all_built_in AS (
    -- everything arriving, plus any core event that did not arrive
    SELECT event_name FROM arriving
    UNION DISTINCT
    SELECT event_name FROM core
)
SELECT
    all_built_in.event_name                AS built_in_event,
    coalesce(arriving.events_in_period, 0)  AS events_in_period,
    if(coalesce(arriving.events_in_period, 0) = 0,
       'Not arriving (unused, or filtered out?)',
       'OK')                                AS status
FROM all_built_in
LEFT JOIN arriving ON all_built_in.event_name = arriving.event_name
ORDER BY if(events_in_period = 0, 0, 1) ASC, events_in_period DESC
LIMIT 200"""

# NEW_QUERY reads this event and OLD_QUERY doesn't. bulk_update skips save(), so the migration adds it to each copy's
# query metadata. Without it, filtering insights by $feature_flag_called doesn't find the rewritten copies.
NEW_QUERY_EVENT = "$feature_flag_called"


def _with_new_query_event(query_metadata, updated_at):
    # A copy's metadata also records the property filters saved on the tile, so the migration keeps it and adds only
    # the event. A copy without metadata keeps none, so the metadata backfill generates it from the whole query.
    if not isinstance(query_metadata, dict) or not isinstance(query_metadata.get("events"), list):
        return query_metadata
    events = sorted({*query_metadata["events"], NEW_QUERY_EVENT})
    return {**query_metadata, "events": events, "updated_at": updated_at}


def fix_health_check_tile_copies(apps, schema_editor):
    Insight = apps.get_model("product_analytics", "Insight")
    db_alias = schema_editor.connection.alias
    updated_at = timezone.now().isoformat().replace("+00:00", "Z")
    copies = Insight.objects.using(db_alias).filter(query__source__query=OLD_QUERY)

    # The query column has no index for this filter, so scan the table once and batch over the ids.
    insight_ids = sorted(copies.values_list("id", flat=True))

    for start in range(0, len(insight_ids), BATCH_SIZE):
        # The filter runs again under the row lock, so a copy that someone edits after the scan keeps its edit.
        insights = list(
            copies.select_for_update(no_key=True)
            .filter(id__in=insight_ids[start : start + BATCH_SIZE])
            .order_by("id")
            .only("id", "query", "query_metadata")
        )
        for insight in insights:
            insight.query["source"]["query"] = NEW_QUERY
            insight.query_metadata = _with_new_query_event(insight.query_metadata, updated_at)
        Insight.objects.using(db_alias).bulk_update(insights, ["query", "query_metadata"])


class Migration(migrations.Migration):
    dependencies = [
        ("product_analytics", "0015_insightagentread"),
    ]

    operations = [
        migrations.RunPython(fix_health_check_tile_copies, migrations.RunPython.noop),
    ]
