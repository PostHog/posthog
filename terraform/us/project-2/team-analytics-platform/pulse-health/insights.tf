# =============================================================================
# Pulse health insights.
#
# Every query reads only pulse capture events. The panel <-> event contract
# (including which properties come from the helpfulness-voting work) is
# documented in README.md next to this file.
# =============================================================================

locals {
  # Row budgets (with 2x margin): series count * time buckets.
  pulse_generation_volume_limit = 6 * 28 * 2 # 3 statuses * 2 triggers * 28 days
  pulse_action_rate_limit       = 2 * 28 * 2 # 2 metrics * 28 days
  pulse_brief_feedback_limit    = 4 * 12 * 2 # helpful/not * goal/no-goal * 12 weeks
  pulse_opp_feedback_limit      = 6 * 12 * 2 # 3 kinds * helpful/not * 12 weeks
  pulse_attention_limit         = 2 * 13 * 2 # 2 metrics * 13 weeks
  pulse_survival_limit          = 28 * 2     # 1 metric * 28 days
  pulse_step_distribution_limit = 50         # distinct step counts (bounded in practice)
  pulse_emit_health_limit       = 28 * 2     # 1 metric * 28 days
}

# ---------------------------------------------------------------------------
# 1. Generation volume + status split.
# ---------------------------------------------------------------------------
resource "posthog_insight" "pulse_generation_volume" {
  name        = "Pulse: Brief generation volume"
  description = "Daily product_brief_generated counts, split by status (ready / quiet / failed) and trigger (on_demand / scheduled)."
  query_json = jsonencode({
    kind = "DataVisualizationNode"
    source = {
      kind  = "HogQLQuery"
      query = <<-SQL
        SELECT
            toDate(timestamp) AS day,
            concat(coalesce(properties.status, 'unknown'), ' · ', coalesce(properties.trigger, 'unknown')) AS series,
            count() AS briefs
        FROM events
        WHERE event = 'product_brief_generated'
          AND timestamp >= now() - INTERVAL 28 DAY
        GROUP BY day, series
        ORDER BY day ASC, series ASC
        LIMIT ${local.pulse_generation_volume_limit}
      SQL
    }
    display = "ActionsBar"
    chartSettings = {
      xAxis = { column = "day" }
      yAxis = [
        {
          column   = "briefs"
          settings = { formatting = { prefix = "", suffix = "" } }
        }
      ]
      seriesBreakdownColumn = "series"
      showLegend            = true
      stackBars100          = false
    }
    tableSettings = {
      columns = [
        { column = "day", settings = { formatting = { prefix = "", suffix = "" } } },
        { column = "series", settings = { formatting = { prefix = "", suffix = "" } } },
        { column = "briefs", settings = { formatting = { prefix = "", suffix = "" } } },
      ]
    }
  })

  dashboard_ids = [posthog_dashboard.pulse_health.id]
  tags          = ["managed-by:terraform", "pulse"]
}

# ---------------------------------------------------------------------------
# 2. Opportunity action rate (the primary adoption metric).
# Acted (and dismissed) opportunities over surfaced opportunities, 7-day
# rolling windows. Surfaced = sum of new_opportunity_count on generation events.
# ---------------------------------------------------------------------------
resource "posthog_insight" "pulse_action_rate" {
  name        = "Pulse: Opportunity action rate (7d rolling)"
  description = "opportunity_acted (and opportunity_dismissed) over opportunities surfaced (sum of new_opportunity_count from product_brief_generated), as 7-day rolling rates."
  query_json = jsonencode({
    kind = "DataVisualizationNode"
    source = {
      kind  = "HogQLQuery"
      query = <<-SQL
        WITH daily AS (
            SELECT
                toDate(timestamp) AS date,
                sumIf(coalesce(toFloat(properties.new_opportunity_count), 0.0), event = 'product_brief_generated') AS surfaced,
                toFloat(countIf(event = 'opportunity_acted')) AS acted,
                toFloat(countIf(event = 'opportunity_dismissed')) AS dismissed
            FROM events
            WHERE event IN ('product_brief_generated', 'opportunity_acted', 'opportunity_dismissed')
              AND timestamp >= now() - INTERVAL 35 DAY
            GROUP BY date
        ),
        date_range AS (
            SELECT toDate(now()) - number AS date FROM numbers(35)
        ),
        base AS (
            SELECT
                d.date AS date,
                coalesce(daily.surfaced, 0.0) AS surfaced,
                coalesce(daily.acted, 0.0) AS acted,
                coalesce(daily.dismissed, 0.0) AS dismissed
            FROM date_range AS d
            LEFT JOIN daily ON d.date = daily.date
        ),
        rolling AS (
            SELECT
                date,
                sum(surfaced) OVER w AS surfaced7,
                sum(acted) OVER w AS acted7,
                sum(dismissed) OVER w AS dismissed7
            FROM base
            WINDOW w AS (ORDER BY date ASC ROWS BETWEEN 6 PRECEDING AND CURRENT ROW)
        )
        SELECT date AS day, metric, value
        FROM (
            SELECT
                date,
                ['Action rate 7d', 'Dismissal rate 7d'] AS metrics,
                [
                    if(surfaced7 > 0, round(acted7 / surfaced7 * 100, 1), NULL),
                    if(surfaced7 > 0, round(dismissed7 / surfaced7 * 100, 1), NULL)
                ] AS vals
            FROM rolling
            WHERE date >= toDate(now()) - 27
        )
        ARRAY JOIN metrics AS metric, vals AS value
        ORDER BY day ASC, metric ASC
        LIMIT ${local.pulse_action_rate_limit}
      SQL
    }
    display = "ActionsLineGraph"
    chartSettings = {
      xAxis = { column = "day" }
      yAxis = [
        {
          column   = "value"
          settings = { formatting = { prefix = "", suffix = "%" } }
        }
      ]
      seriesBreakdownColumn = "metric"
      showLegend            = true
    }
    tableSettings = {
      columns = [
        { column = "day", settings = { formatting = { prefix = "", suffix = "" } } },
        { column = "metric", settings = { formatting = { prefix = "", suffix = "" } } },
        { column = "value", settings = { formatting = { prefix = "", suffix = "%" } } },
      ]
    }
  })

  dashboard_ids = [posthog_dashboard.pulse_health.id]
  tags          = ["managed-by:terraform", "pulse"]
}

# ---------------------------------------------------------------------------
# 3a. Brief helpfulness, split by whether the brief had a focus goal.
# Reads the product_brief_feedback event from helpfulness voting.
# ---------------------------------------------------------------------------
resource "posthog_insight" "pulse_brief_helpfulness" {
  name        = "Pulse: Brief helpfulness"
  description = "Weekly helpful vs not-helpful votes on briefs (product_brief_feedback), split by whether the brief had a focus goal. Charts vote actions per week, not net helpfulness state: revotes count again, and a later-cleared vote still counts in the week it was cast."
  query_json = jsonencode({
    kind = "DataVisualizationNode"
    source = {
      kind  = "HogQLQuery"
      query = <<-SQL
        SELECT
            toStartOfWeek(timestamp) AS week,
            concat(
                if(properties.helpful = 'true', 'Helpful', 'Not helpful'),
                if(properties.has_goal = 'true', ' · goal', ' · no goal')
            ) AS series,
            count() AS votes
        FROM events
        WHERE event = 'product_brief_feedback'
          AND properties.helpful IS NOT NULL
          AND timestamp >= now() - INTERVAL 12 WEEK
        GROUP BY week, series
        ORDER BY week ASC, series ASC
        LIMIT ${local.pulse_brief_feedback_limit}
      SQL
    }
    display = "ActionsBar"
    chartSettings = {
      xAxis = { column = "week" }
      yAxis = [
        {
          column   = "votes"
          settings = { formatting = { prefix = "", suffix = "" } }
        }
      ]
      seriesBreakdownColumn = "series"
      showLegend            = true
    }
    tableSettings = {
      columns = [
        { column = "week", settings = { formatting = { prefix = "", suffix = "" } } },
        { column = "series", settings = { formatting = { prefix = "", suffix = "" } } },
        { column = "votes", settings = { formatting = { prefix = "", suffix = "" } } },
      ]
    }
  })

  dashboard_ids = [posthog_dashboard.pulse_health.id]
  tags          = ["managed-by:terraform", "pulse"]
}

# ---------------------------------------------------------------------------
# 3b. Opportunity helpfulness, split by opportunity kind.
# Reads the opportunity_feedback event from helpfulness voting.
# ---------------------------------------------------------------------------
resource "posthog_insight" "pulse_opportunity_helpfulness" {
  name        = "Pulse: Opportunity helpfulness"
  description = "Weekly helpful vs not-helpful votes on opportunities (opportunity_feedback), split by opportunity kind (build / fix / instrument). Charts vote actions per week, not net helpfulness state: revotes count again, and a later-cleared vote still counts in the week it was cast."
  query_json = jsonencode({
    kind = "DataVisualizationNode"
    source = {
      kind  = "HogQLQuery"
      query = <<-SQL
        SELECT
            toStartOfWeek(timestamp) AS week,
            concat(
                coalesce(properties.kind, 'unknown'),
                if(properties.helpful = 'true', ' · helpful', ' · not helpful')
            ) AS series,
            count() AS votes
        FROM events
        WHERE event = 'opportunity_feedback'
          AND properties.helpful IS NOT NULL
          AND timestamp >= now() - INTERVAL 12 WEEK
        GROUP BY week, series
        ORDER BY week ASC, series ASC
        LIMIT ${local.pulse_opp_feedback_limit}
      SQL
    }
    display = "ActionsBar"
    chartSettings = {
      xAxis = { column = "week" }
      yAxis = [
        {
          column   = "votes"
          settings = { formatting = { prefix = "", suffix = "" } }
        }
      ]
      seriesBreakdownColumn = "series"
      showLegend            = true
    }
    tableSettings = {
      columns = [
        { column = "week", settings = { formatting = { prefix = "", suffix = "" } } },
        { column = "series", settings = { formatting = { prefix = "", suffix = "" } } },
        { column = "votes", settings = { formatting = { prefix = "", suffix = "" } } },
      ]
    }
  })

  dashboard_ids = [posthog_dashboard.pulse_health.id]
  tags          = ["managed-by:terraform", "pulse"]
}

# ---------------------------------------------------------------------------
# 4. Attention retention: weekly unique brief viewers + week-over-week return.
# "Returning viewers" = viewers this week who also viewed a brief last week —
# the honest week-N signal (a viewer counts only if they actually came back).
# ---------------------------------------------------------------------------
resource "posthog_insight" "pulse_attention_retention" {
  name        = "Pulse: Attention retention"
  description = "Weekly unique viewers of product_brief_viewed, alongside how many of them also viewed a brief the previous week. The current (partial) week undercounts until it ends."
  query_json = jsonencode({
    kind = "DataVisualizationNode"
    source = {
      kind  = "HogQLQuery"
      query = <<-SQL
        WITH viewer_weeks AS (
            SELECT
                person_id,
                groupUniqArray(toStartOfWeek(timestamp)) AS weeks
            FROM events
            WHERE event = 'product_brief_viewed'
              AND timestamp >= now() - INTERVAL 14 WEEK
            GROUP BY person_id
        ),
        expanded AS (
            SELECT person_id, weeks, arrayJoin(weeks) AS week
            FROM viewer_weeks
        )
        SELECT week AS time, metric, value
        FROM (
            -- Scan one week more than we display so the oldest displayed week
            -- has a real previous week to compute "Returning viewers" against.
            SELECT
                week,
                ['Weekly viewers', 'Returning viewers'] AS metrics,
                [
                    toFloat(uniqExact(person_id)),
                    toFloat(uniqExactIf(person_id, has(weeks, week - INTERVAL 7 DAY)))
                ] AS vals
            FROM expanded
            WHERE week >= toStartOfWeek(now() - INTERVAL 13 WEEK)
            GROUP BY week
        )
        ARRAY JOIN metrics AS metric, vals AS value
        ORDER BY time ASC, metric ASC
        LIMIT ${local.pulse_attention_limit}
      SQL
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
    }
    tableSettings = {
      columns = [
        { column = "time", settings = { formatting = { prefix = "", suffix = "" } } },
        { column = "metric", settings = { formatting = { prefix = "", suffix = "" } } },
        { column = "value", settings = { formatting = { prefix = "", suffix = "" } } },
      ]
    }
  })

  dashboard_ids = [posthog_dashboard.pulse_health.id]
  tags          = ["managed-by:terraform", "pulse"]
}

# ---------------------------------------------------------------------------
# 5a. Investigation step survival rate: 1 - (failed steps / total steps).
# ---------------------------------------------------------------------------
resource "posthog_insight" "pulse_investigation_survival" {
  name        = "Pulse: Investigation step survival rate"
  description = "Daily share of investigation steps that succeeded (1 - failed/total) across product_brief_generated events with at least one step."
  query_json = jsonencode({
    kind = "DataVisualizationNode"
    source = {
      kind  = "HogQLQuery"
      query = <<-SQL
        SELECT
            toDate(timestamp) AS day,
            round(
                (1 - sum(coalesce(toFloat(properties.investigation_failed_count), 0.0))
                   / sum(toFloat(properties.investigation_step_count))) * 100,
                1
            ) AS survival_rate
        FROM events
        WHERE event = 'product_brief_generated'
          AND toFloat(properties.investigation_step_count) > 0
          AND timestamp >= now() - INTERVAL 28 DAY
        GROUP BY day
        ORDER BY day ASC
        LIMIT ${local.pulse_survival_limit}
      SQL
    }
    display = "ActionsLineGraph"
    chartSettings = {
      xAxis = { column = "day" }
      yAxis = [
        {
          column   = "survival_rate"
          settings = { formatting = { prefix = "", suffix = "%" } }
        }
      ]
    }
    tableSettings = {
      columns = [
        { column = "day", settings = { formatting = { prefix = "", suffix = "" } } },
        { column = "survival_rate", settings = { formatting = { prefix = "", suffix = "%" } } },
      ]
    }
  })

  dashboard_ids = [posthog_dashboard.pulse_health.id]
  tags          = ["managed-by:terraform", "pulse"]
}

# ---------------------------------------------------------------------------
# 5b. Investigation step-count distribution (the truncation watch item:
# a pile-up at the step cap means investigations are getting cut off).
# ---------------------------------------------------------------------------
resource "posthog_insight" "pulse_investigation_steps" {
  name        = "Pulse: Investigation step-count distribution"
  description = "How many briefs ran N investigation steps over the last 28 days. A spike at the maximum means investigations are being truncated."
  query_json = jsonencode({
    kind = "DataVisualizationNode"
    source = {
      kind  = "HogQLQuery"
      query = <<-SQL
        SELECT
            coalesce(toInt(properties.investigation_step_count), 0) AS steps,
            count() AS briefs
        FROM events
        WHERE event = 'product_brief_generated'
          AND timestamp >= now() - INTERVAL 28 DAY
        GROUP BY steps
        ORDER BY steps ASC
        LIMIT ${local.pulse_step_distribution_limit}
      SQL
    }
    display = "ActionsBar"
    chartSettings = {
      xAxis = { column = "steps" }
      yAxis = [
        {
          column   = "briefs"
          settings = { formatting = { prefix = "", suffix = "" } }
        }
      ]
    }
    tableSettings = {
      columns = [
        { column = "steps", settings = { formatting = { prefix = "", suffix = "" } } },
        { column = "briefs", settings = { formatting = { prefix = "", suffix = "" } } },
      ]
    }
  })

  dashboard_ids = [posthog_dashboard.pulse_health.id]
  tags          = ["managed-by:terraform", "pulse"]
}

# ---------------------------------------------------------------------------
# 6. Signal emit health: emit failures over opportunities emitted.
# emit_failed_count coalesces to 0 for events captured before the property
# existed, so early history reads as a 0% failure rate.
# ---------------------------------------------------------------------------
resource "posthog_insight" "pulse_emit_health" {
  name        = "Pulse: Signal emit failure rate (7d rolling)"
  description = "emit_failed_count over new_opportunity_count from product_brief_generated, as a 7-day rolling failure rate. Emits are best-effort, so failures never fail the brief — this chart is where they become visible."
  query_json = jsonencode({
    kind = "DataVisualizationNode"
    source = {
      kind  = "HogQLQuery"
      query = <<-SQL
        WITH daily AS (
            SELECT
                toDate(timestamp) AS date,
                sum(coalesce(toFloat(properties.new_opportunity_count), 0.0)) AS emitted,
                sum(coalesce(toFloat(properties.emit_failed_count), 0.0)) AS failed
            FROM events
            WHERE event = 'product_brief_generated'
              AND timestamp >= now() - INTERVAL 35 DAY
            GROUP BY date
        ),
        date_range AS (
            SELECT toDate(now()) - number AS date FROM numbers(35)
        ),
        base AS (
            SELECT
                d.date AS date,
                coalesce(daily.emitted, 0.0) AS emitted,
                coalesce(daily.failed, 0.0) AS failed
            FROM date_range AS d
            LEFT JOIN daily ON d.date = daily.date
        ),
        rolling AS (
            SELECT
                date,
                sum(emitted) OVER w AS emitted7,
                sum(failed) OVER w AS failed7
            FROM base
            WINDOW w AS (ORDER BY date ASC ROWS BETWEEN 6 PRECEDING AND CURRENT ROW)
        )
        SELECT
            date AS day,
            if(emitted7 > 0, round(failed7 / emitted7 * 100, 1), NULL) AS emit_failure_rate
        FROM rolling
        WHERE date >= toDate(now()) - 27
        ORDER BY day ASC
        LIMIT ${local.pulse_emit_health_limit}
      SQL
    }
    display = "ActionsLineGraph"
    chartSettings = {
      xAxis = { column = "day" }
      yAxis = [
        {
          column   = "emit_failure_rate"
          settings = { formatting = { prefix = "", suffix = "%" } }
        }
      ]
    }
    tableSettings = {
      columns = [
        { column = "day", settings = { formatting = { prefix = "", suffix = "" } } },
        { column = "emit_failure_rate", settings = { formatting = { prefix = "", suffix = "%" } } },
      ]
    }
  })

  dashboard_ids = [posthog_dashboard.pulse_health.id]
  tags          = ["managed-by:terraform", "pulse"]
}
