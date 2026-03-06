locals {
  slo_base_query = <<-SQL
    WITH
        date_range AS (SELECT toDate(now()) - number AS date FROM numbers(30)),
        daily AS (
            {{DAILY_SQL}}
        ),
        base AS (
            SELECT
                d.date,
                coalesce(daily.total, 0)    AS total,
                coalesce(daily.failures, 0) AS failures
            FROM date_range d
            LEFT JOIN daily ON d.date = daily.date
        ),
        rolling AS (
            SELECT
                date,
                sum(failures) OVER w1  AS f1,  sum(total) OVER w1  AS t1,
                sum(failures) OVER w7  AS f7,  sum(total) OVER w7  AS t7,
                sum(failures) OVER w30 AS f30, sum(total) OVER w30 AS t30
            FROM base
            WINDOW
                w1  AS (ORDER BY date ASC ROWS BETWEEN 0 PRECEDING AND CURRENT ROW),
                w7  AS (ORDER BY date ASC ROWS BETWEEN 6 PRECEDING AND CURRENT ROW),
                w30 AS (ORDER BY date ASC ROWS BETWEEN 29 PRECEDING AND CURRENT ROW)
        )
    SELECT date, metric, value
    FROM (
        SELECT
            date,
            ['Burn rate 1d', 'Burn rate 7d', 'Burn rate 30d', 'Success rate 30d'] AS metrics,
            [
                round(if(t1  > 0, f1  / t1  / {{ERROR_BUDGET}}, 0), 2),
                round(if(t7  > 0, f7  / t7  / {{ERROR_BUDGET}}, 0), 2),
                round(if(t30 > 0, f30 / t30 / {{ERROR_BUDGET}}, 0), 2),
                round(if(t30 > 0, (t30 - f30) / t30 * 100, 0), 2)
            ] AS values
        FROM rolling
    )
    ARRAY JOIN metrics AS metric, values AS value
    ORDER BY date ASC, metric ASC
    LIMIT 500
  SQL

  # -----------------------------------------------------------------------
  # Region-specific table names. All SQL templates use {{TOKEN}}
  # placeholders which are replaced per region.
  # -----------------------------------------------------------------------

  region_tables = {
    us = {
      events_table  = "events"
      exports_table = "postgres.posthog_exportedasset"
      history_table = "system.cohort_calculation_history"
    }
    eu = {
      events_table  = "eu_events"
      exports_table = "eu_posthog_exportedasset"
      history_table = "eu_system.cohort_calculation_history"
    }
  }

  # -----------------------------------------------------------------------
  # SLO definitions. Each daily_sql must return (date, total, failures).
  # Token replacement uses the centralized region_tables above — all tokens
  # are replaced on every template (unused tokens are no-ops).
  # -----------------------------------------------------------------------

  slo_definitions = {
    alerts = {
      name_prefix  = "SLO: Alert checks"
      description  = "Rolling burn rate and 30d success rate for alert checks."
      error_budget = 0.01
      daily_sql    = <<-SQL
        SELECT
            toDate(timestamp) AS date,
            countIf(event = 'alert check') AS total,
            countIf(event = 'alert check failed') AS failures
        FROM {{EVENTS_TABLE}}
        WHERE event IN ('alert check', 'alert check failed')
            AND timestamp >= now() - INTERVAL 30 DAY
        GROUP BY date
      SQL
    }

    # Timeliness: did each alert fire within its scheduled interval?
    # Tolerances (exact interval window):
    #   hourly  <= 60 min,   daily   <= 24 h (1440 min),
    #   weekly  <= 7 d (10080 min),  monthly <= 31 d (44640 min)
    # Uses lagInFrame to compute gap between consecutive checks per alert.
    # Looks back 45 days so monthly alerts have a valid prev_check in the 30-day window.
    alerts_timeliness = {
      name_prefix  = "SLO: Alert timeliness"
      description  = "Timeliness SLO: % of alert checks that fired within their scheduled interval."
      error_budget = 0.01
      daily_sql    = <<-SQL
        WITH alert_checks AS (
            SELECT
                properties.alert_id AS alert_id,
                properties.calculation_interval AS calculation_interval,
                timestamp,
                lagInFrame(timestamp) OVER (
                    PARTITION BY properties.alert_id, properties.calculation_interval
                    ORDER BY timestamp ASC
                    ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
                ) AS prev_check
            FROM {{EVENTS_TABLE}}
            WHERE event IN ('alert check', 'alert check failed')
                AND properties.calculation_interval IN ('hourly', 'daily', 'weekly', 'monthly')
                AND timestamp >= now() - INTERVAL 45 DAY
        )
        SELECT
            toDate(timestamp) AS date,
            count()           AS total,
            countIf(
                (calculation_interval = 'hourly'  AND dateDiff('minute', prev_check, timestamp) > 60)    OR
                (calculation_interval = 'daily'   AND dateDiff('minute', prev_check, timestamp) > 1440)  OR
                (calculation_interval = 'weekly'  AND dateDiff('minute', prev_check, timestamp) > 10080) OR
                (calculation_interval = 'monthly' AND dateDiff('minute', prev_check, timestamp) > 44640)
            ) AS failures
        FROM alert_checks
        WHERE prev_check != toDateTime(0)
            AND toDate(timestamp) >= toDate(now()) - 30
        GROUP BY date
      SQL
    }

    # 10-minute grace period excludes in-progress exports that haven't
    # had time to produce output yet.
    exports = {
      name_prefix  = "SLO: Exports"
      description  = "Rolling burn rate and 30d success rate for exports."
      error_budget = 0.01
      daily_sql    = <<-SQL
        SELECT
            toDate(created_at) AS date,
            count() AS total,
            countIf(export_context IS NULL AND content_location IS NULL) AS failures
        FROM {{EXPORTS_TABLE}}
        WHERE created_at >= now() - INTERVAL 30 DAY
            AND created_at < now() - INTERVAL 10 MINUTE
        GROUP BY date
      SQL
    }

    # Cohorts not calculated within a day count as failures.
    cohorts = {
      name_prefix  = "SLO: Cohort calculations"
      description  = "Rolling burn rate and 30d success rate for cohort calculations. Cohorts not calculated within a day count as failures."
      error_budget = 0.01
      daily_sql    = <<-SQL
        SELECT
            cc.date,
            count() AS total,
            count() - countIf(dc.successes > 0) AS failures
        FROM (
            SELECT d.date, c.cohort_id
            FROM (SELECT toDate(now()) - number AS date FROM numbers(37)) d
            CROSS JOIN (
                SELECT cohort_id, min(toDate(finished_at)) AS first_seen
                FROM {{HISTORY_TABLE}}
                WHERE finished_at >= now() - INTERVAL 37 DAY
                GROUP BY cohort_id
            ) c
            WHERE c.first_seen <= d.date
        ) cc
        LEFT JOIN (
            SELECT
                toDate(finished_at) AS date,
                cohort_id,
                countIf(error_code IS NULL OR error_code = '') AS successes
            FROM {{HISTORY_TABLE}}
            WHERE finished_at >= now() - INTERVAL 30 DAY
                AND finished_at IS NOT NULL
            GROUP BY date, cohort_id
        ) dc ON cc.date = dc.date AND cc.cohort_id = dc.cohort_id
        WHERE cc.date >= toDate(now()) - 30
        GROUP BY cc.date
      SQL
    }
  }

  # Flatten: creates keys like "alerts_us", "alerts_eu", "exports_us", etc.
  # All region tokens are replaced on every template — tokens that don't
  # appear in a given template are harmless no-ops.
  slo_insights = merge([
    for slo_key, slo in local.slo_definitions : {
      for region in keys(local.region_tables) :
      "${slo_key}_${region}" => {
        name         = "${slo.name_prefix} (${upper(region)})"
        description  = slo.description
        error_budget = slo.error_budget
        daily_sql = replace(
          replace(
            replace(slo.daily_sql,
              "{{EVENTS_TABLE}}", local.region_tables[region].events_table),
            "{{EXPORTS_TABLE}}", local.region_tables[region].exports_table),
          "{{HISTORY_TABLE}}", local.region_tables[region].history_table)
      }
    }
  ]...)
}

resource "posthog_insight" "slo" {
  for_each = local.slo_insights

  name        = each.value.name
  description = each.value.description
  query_json = jsonencode({
    kind = "DataVisualizationNode"
    source = {
      kind  = "HogQLQuery"
      query = replace(
        replace(local.slo_base_query, "{{DAILY_SQL}}", each.value.daily_sql),
        "{{ERROR_BUDGET}}", tostring(each.value.error_budget)
      )
    }
    display = "ActionsLineGraph"
    chartSettings = {
      xAxis = { column = "date" }
      yAxis = [
        {
          column   = "value"
          settings = { formatting = { prefix = "", suffix = "" } }
        }
      ]
      seriesBreakdownColumn = "metric"
      showLegend            = true
    }
    tableSettings = {
      columns = [
        { column = "date",   settings = { formatting = { prefix = "", suffix = "" } } },
        { column = "metric", settings = { formatting = { prefix = "", suffix = "" } } },
        { column = "value",  settings = { formatting = { prefix = "", suffix = "%" } } },
      ]
    }
  })

  dashboard_ids = [posthog_dashboard.team_analytics_platform_slos.id]
  tags          = ["managed-by:terraform", "slo"]
}
