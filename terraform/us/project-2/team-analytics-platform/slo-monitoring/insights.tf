locals {
  # ===========================================================================
  # SLO operation config. Add new operations here to auto-generate insights.
  # Each operation must emit slo_operation_started and slo_operation_completed
  # events with matching properties.operation value (see posthog/slo/types.py).
  # ===========================================================================
  slo_operations = {
    export = {
      name    = "Exports"
      slo     = 99.95 # error budget = 0.05%
      regions = ["US", "EU"]
    }
    subscription_delivery = {
      name    = "Subscription deliveries"
      slo     = 99.95 # error budget = 0.05%
      regions = ["US", "EU"]
    }
    subscription_create = {
      name    = "Subscription created"
      slo     = 99.95 # error budget = 0.05%
      regions = ["US", "EU"]
    }
    subscription_delete = {
      name    = "Subscription deleted"
      slo     = 99.95 # error budget = 0.05%
      regions = ["US", "EU"]
    }
    alert_check = {
      name    = "Alert checks"
      slo     = 99.95 # error budget = 0.05%
      regions = ["US"] # EU not captured yet: ph_scoped_capture hardcodes US client
    }
  }

  # ---------------------------------------------------------------------------
  # Flatten: {operation}_{region} for burn rate + duration per region.
  # ---------------------------------------------------------------------------
  slo_operation_regions = merge([
    for op_key, op in local.slo_operations : {
      for region in op.regions :
      "${op_key}_${lower(region)}" => {
        name         = op.name
        slo          = op.slo
        operation    = op_key
        region       = region
        region_count = length(op.regions)
      }
    }
  ]...)

  # Row budgets for queries (with 2x margin for safety).
  slo_burn_rate_limit    = 168 * 4 * 2 # 7 days * 24h * 4 metrics * margin
  slo_duration_limit     = 7 * 3 * 2   # 7 days * 3 percentiles * margin
  slo_success_rate_limit = length(local.slo_operations) * 28 * 2

  # Explicit operation list for the success rate query (avoids DISTINCT drift).
  slo_operation_list = join(", ", [for k, _ in local.slo_operations : "'${k}'"])

  # ---------------------------------------------------------------------------
  # Burn rate query template (hourly granularity, 4 windows).
  # Placeholders: {{OPERATION}}, {{REGION}}, {{ERROR_BUDGET}}
  # ---------------------------------------------------------------------------
  slo_burn_rate_query = <<-SQL
    -- Single scan: GROUP BY (cid, hour) extracts correlation_id once per row.
    -- Correlated events (cid != '') are paired by cid then attributed to start hour.
    -- Uncorrelated events (cid = '') use bucket-based counting with clamp.
    WITH per_cid_hour AS (
        SELECT
            coalesce(nullIf(properties.correlation_id, ''), '') AS cid,
            toStartOfHour(timestamp) AS event_hour,
            countIf(event = 'slo_operation_started') AS starts,
            countIf(event = 'slo_operation_completed' AND properties.outcome = 'success') AS successes,
            min(if(event = 'slo_operation_started', timestamp, NULL)) AS first_start
        FROM events
        WHERE event IN ('slo_operation_started', 'slo_operation_completed')
          AND properties.operation = '{{OPERATION}}'
          AND properties.region = '{{REGION}}'
          AND timestamp >= now() - INTERVAL 35 DAY
        GROUP BY cid, event_hour
    ),
    hourly AS (
        SELECT hour, sum(total) AS total, sum(failures) AS failures
        FROM (
            -- Uncorrelated: each row is one hour bucket, clamp failures to 0
            SELECT
                event_hour AS hour,
                starts AS total,
                greatest(starts - successes, 0) AS failures
            FROM per_cid_hour
            WHERE cid = ''

            UNION ALL

            -- Correlated: collapse across hours per cid, attribute to start hour
            SELECT
                toStartOfHour(min(first_start)) AS hour,
                1 AS total,
                if(max(successes) > 0, 0, 1) AS failures
            FROM per_cid_hour
            WHERE cid != ''
            GROUP BY cid
            HAVING hour IS NOT NULL
        )
        GROUP BY hour
    ),
    hour_range AS (
        SELECT toStartOfHour(now()) - INTERVAL number HOUR AS hour FROM numbers(841)
    ),
    base AS (
        SELECT
            h.hour AS hour,
            coalesce(hourly.total, 0) AS total,
            coalesce(hourly.failures, 0) AS failures
        FROM hour_range AS h
        LEFT JOIN hourly ON h.hour = hourly.hour
    ),
    rolling AS (
        SELECT
            hour,
            total AS t1h,
            failures AS f1h,
            sum(total) OVER w24h AS t24h,
            sum(failures) OVER w24h AS f24h,
            sum(total) OVER w7d AS t7d,
            sum(failures) OVER w7d AS f7d,
            sum(total) OVER w28d AS t28d,
            sum(failures) OVER w28d AS f28d
        FROM base
        WINDOW
            w24h AS (ORDER BY hour ASC ROWS BETWEEN 23 PRECEDING AND CURRENT ROW),
            w7d  AS (ORDER BY hour ASC ROWS BETWEEN 167 PRECEDING AND CURRENT ROW),
            w28d AS (ORDER BY hour ASC ROWS BETWEEN 671 PRECEDING AND CURRENT ROW)
    )
    SELECT hour AS time, metric, value
    FROM (
        SELECT
            hour,
            if(t1h  > 0, round((f1h  / t1h)  / {{ERROR_BUDGET}}, 2), NULL) AS raw_1h,
            if(t24h > 0, round((f24h / t24h) / {{ERROR_BUDGET}}, 2), NULL) AS raw_24h,
            if(t7d  > 0, round((f7d  / t7d)  / {{ERROR_BUDGET}}, 2), NULL) AS raw_7d,
            if(t28d > 0, round((f28d / t28d) / {{ERROR_BUDGET}}, 2), NULL) AS raw_28d,
            ['Burn rate 1h', 'Burn rate 24h', 'Burn rate 7d', 'Burn rate 28d'] AS metrics,
            [
                sign(raw_1h)  * log10(1 + abs(raw_1h)),
                sign(raw_24h) * log10(1 + abs(raw_24h)),
                sign(raw_7d)  * log10(1 + abs(raw_7d)),
                sign(raw_28d) * log10(1 + abs(raw_28d))
            ] AS vals
        FROM rolling
        WHERE hour >= now() - INTERVAL 7 DAY
    )
    ARRAY JOIN metrics AS metric, vals AS value
    ORDER BY time ASC, metric ASC
    LIMIT ${local.slo_burn_rate_limit}
  SQL

  # ---------------------------------------------------------------------------
  # Duration percentile query template (daily granularity, p50/p95/p99 in seconds).
  # Placeholders: {{OPERATION}}, {{REGION}}
  # ---------------------------------------------------------------------------
  slo_duration_query = <<-SQL
    WITH daily AS (
        SELECT
            toDate(timestamp) AS date,
            quantile(0.50)(toFloat(properties.duration_ms)) / 1000 AS p50,
            quantile(0.95)(toFloat(properties.duration_ms)) / 1000 AS p95,
            quantile(0.99)(toFloat(properties.duration_ms)) / 1000 AS p99
        FROM events
        WHERE event = 'slo_operation_completed'
          AND properties.operation = '{{OPERATION}}'
          AND properties.region = '{{REGION}}'
          AND properties.duration_ms IS NOT NULL
          AND timestamp >= now() - INTERVAL 7 DAY
        GROUP BY date
    ),
    date_range AS (
        SELECT toDate(now()) - number AS date FROM numbers(7)
    ),
    base AS (
        SELECT
            d.date AS date,
            daily.p50,
            daily.p95,
            daily.p99
        FROM date_range AS d
        LEFT JOIN daily ON d.date = daily.date
    )
    SELECT date AS day, metric, value
    FROM (
        SELECT
            date,
            ['p50', 'p95', 'p99'] AS metrics,
            [
                round(p50, 1),
                round(p95, 1),
                round(p99, 1)
            ] AS vals
        FROM base
    )
    ARRAY JOIN metrics AS metric, vals AS value
    ORDER BY day ASC, metric ASC
    LIMIT ${local.slo_duration_limit}
  SQL

}

# ---------------------------------------------------------------------------
# Burn rate insights (one per operation, auto-generated).
# ---------------------------------------------------------------------------
resource "posthog_insight" "slo_burn_rate" {
  for_each = local.slo_operation_regions

  name        = "SLO: Burn Rates - ${each.value.name} (${each.value.slo}%)${each.value.region_count > 1 ? " — ${each.value.region}" : ""}"
  description = "[Investigate failures with AI](/ai?ask=Investigate+${each.value.operation}+failures+in+${each.value.region}+region.+Check+slo_operation_started+events+without+matching+slo_operation_completed+success+outcomes+in+the+last+24h)"
  query_json = jsonencode({
    kind = "DataVisualizationNode"
    source = {
      kind = "HogQLQuery"
      query = replace(
        replace(
          replace(local.slo_burn_rate_query, "{{OPERATION}}", each.value.operation),
          "{{REGION}}", each.value.region),
        "{{ERROR_BUDGET}}", tostring((100 - each.value.slo) / 100)
      )
    }
    display = "ActionsLineGraph"
    chartSettings = {
      xAxis = { column = "time" }
      yAxis = [
        {
          column   = "value"
          settings = { formatting = { prefix = "", suffix = "" } }
        }
      ]
      seriesBreakdownColumn = "metric"
      showLegend            = true
      goalLines = [
        { label = "Budget rate", value = 0.30, position = "start" },
        { label = "100x burn",   value = 2.00, position = "start" }
      ]
    }
    tableSettings = {
      columns = [
        { column = "time", settings = { formatting = { prefix = "", suffix = "" } } },
        { column = "metric", settings = { formatting = { prefix = "", suffix = "" } } },
        { column = "value", settings = { formatting = { prefix = "", suffix = "" } } },
      ]
    }
  })

  dashboard_ids = [posthog_dashboard.slo_monitoring.id]
  tags          = ["managed-by:terraform", "slo"]
}

# ---------------------------------------------------------------------------
# Duration percentile insights (one per operation, auto-generated).
# ---------------------------------------------------------------------------
resource "posthog_insight" "slo_duration" {
  for_each = local.slo_operation_regions

  name        = "SLO: Duration - ${each.value.name}${each.value.region_count > 1 ? " — ${each.value.region}" : ""}"
  query_json = jsonencode({
    kind = "DataVisualizationNode"
    source = {
      kind  = "HogQLQuery"
      query = replace(
        replace(local.slo_duration_query, "{{OPERATION}}", each.value.operation),
        "{{REGION}}", each.value.region)
    }
    display = "ActionsAreaGraph"
    chartSettings = {
      xAxis = { column = "day" }
      yAxis = [
        {
          column = "value"
          settings = {
            display    = { color = "#1d4aff", label = "", trendLine = false, displayType = "auto", yAxisPosition = "left" }
            formatting = { style = "number", prefix = "", suffix = "s" }
          }
        }
      ]
      seriesBreakdownColumn = "metric"
    }
    tableSettings = {
      columns = [
        { column = "day", settings = { formatting = { prefix = "", suffix = "" } } },
        { column = "metric", settings = { formatting = { prefix = "", suffix = "" } } },
        { column = "value", settings = { formatting = { style = "number", prefix = "", suffix = "s" } } },
      ]
    }
  })

  dashboard_ids = [posthog_dashboard.slo_monitoring.id]
  tags          = ["managed-by:terraform", "slo"]
}

# ---------------------------------------------------------------------------
# Combined 28d success rate (all operations on one chart).
# ---------------------------------------------------------------------------
resource "posthog_insight" "slo_success_rate" {
  name        = "SLO: 28d Success Rate"
  query_json = jsonencode({
    kind = "DataVisualizationNode"
    source = {
      kind  = "HogQLQuery"
      query = <<-SQL
        -- No correlation_id needed: daily buckets have negligible cross-bucket issues.
        WITH daily AS (
            SELECT
                toDate(timestamp) AS date,
                properties.operation AS operation,
                countIf(event = 'slo_operation_started') AS total,
                greatest(
                    countIf(event = 'slo_operation_started')
                      - countIf(event = 'slo_operation_completed' AND properties.outcome = 'success'),
                    0
                ) AS failures
            FROM events
            WHERE event IN ('slo_operation_started', 'slo_operation_completed')
              AND properties.operation IN (${local.slo_operation_list})
              AND timestamp >= now() - INTERVAL 56 DAY
            GROUP BY date, operation
        ),
        date_range AS (
            SELECT toDate(now()) - number AS date FROM numbers(28)
        ),
        operations AS (
            SELECT arrayJoin([${local.slo_operation_list}]) AS operation
        ),
        base AS (
            SELECT
                d.date AS date,
                o.operation AS operation,
                coalesce(daily.total, 0) AS total,
                coalesce(daily.failures, 0) AS failures
            FROM date_range AS d
            CROSS JOIN operations AS o
            LEFT JOIN daily ON d.date = daily.date AND o.operation = daily.operation
        ),
        rolling AS (
            SELECT
                date,
                operation,
                sum(total) OVER (PARTITION BY operation ORDER BY date ASC ROWS BETWEEN 27 PRECEDING AND CURRENT ROW) AS t28,
                sum(failures) OVER (PARTITION BY operation ORDER BY date ASC ROWS BETWEEN 27 PRECEDING AND CURRENT ROW) AS f28
            FROM base
        )
        SELECT
            date AS day,
            operation,
            if(t28 > 0, round((t28 - f28) / t28 * 100, 2), NULL) AS success_rate
        FROM rolling
        ORDER BY date ASC, operation ASC
        LIMIT ${local.slo_success_rate_limit}
      SQL
    }
    display = "ActionsLineGraph"
    chartSettings = {
      xAxis = { column = "day" }
      yAxis = [
        {
          column   = "success_rate"
          settings = { formatting = { prefix = "", suffix = "%" } }
        }
      ]
      seriesBreakdownColumn = "operation"
      showLegend            = true
    }
    tableSettings = {
      columns = [
        { column = "day", settings = { formatting = { prefix = "", suffix = "" } } },
        { column = "operation", settings = { formatting = { prefix = "", suffix = "" } } },
        { column = "success_rate", settings = { formatting = { prefix = "", suffix = "%" } } },
      ]
    }
  })

  dashboard_ids = [posthog_dashboard.slo_monitoring.id]
  tags          = ["managed-by:terraform", "slo"]
}

# ---------------------------------------------------------------------------
# 28d volume summary table (all operations, includes SLO target).
# ---------------------------------------------------------------------------
resource "posthog_insight" "slo_volume" {
  name        = "SLO: 28d Volume by Operation"
  description = "* = all regions, but events are only emitted from the US project (ph_scoped_capture hardcodes the US client)"
  query_json = jsonencode({
    kind = "DataVisualizationNode"
    source = {
      kind  = "HogQLQuery"
      query = <<-SQL
        -- No correlation_id needed: single 28-day bucket has no cross-bucket issue.
        SELECT
            properties.operation AS operation,
            if(
                count(properties.region) OVER (PARTITION BY properties.operation) = 1,
                'all*',
                properties.region
            ) AS region,
            countIf(event = 'slo_operation_started') AS started,
            countIf(event = 'slo_operation_completed' AND properties.outcome = 'success') AS successes,
            countIf(event = 'slo_operation_completed' AND properties.outcome = 'failure') AS failures,
            greatest(
                countIf(event = 'slo_operation_started')
                  - countIf(event = 'slo_operation_completed'),
                0
            ) AS never_completed,
            if(
                countIf(event = 'slo_operation_started') > 0,
                round(countIf(event = 'slo_operation_completed' AND properties.outcome = 'success')
                  / countIf(event = 'slo_operation_started') * 100, 2),
                NULL
            ) AS success_rate
        FROM events
        WHERE event IN ('slo_operation_started', 'slo_operation_completed')
          AND timestamp >= now() - INTERVAL 28 DAY
        GROUP BY operation, properties.region
        ORDER BY operation, region
      SQL
    }
  })

  dashboard_ids = [posthog_dashboard.slo_monitoring.id]
  tags          = ["managed-by:terraform", "slo"]
}
