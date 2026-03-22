import {
  to = posthog_dashboard_layout.team_analytics_platform_slos
  id = "2/1333288"
}

resource "posthog_dashboard_layout" "team_analytics_platform_slos" {
  dashboard_id = posthog_dashboard.team_analytics_platform_slos.id
  tiles = [
    {
      insight_id = posthog_insight.slo_success_rates.id
      layouts_json = jsonencode({
        sm = {
          h      = 5
          i      = "0"
          w      = 12
          x      = 0
          y      = 0
          minH   = 1
          minW   = 1
          moved  = false
          static = false
        }
      })
    },
    {
      text_body = "**Success rate** is a 30-day rolling window showing the percentage of successful operations per SLO. **Burn rate** (below) measures how fast you're consuming your error budget — 1.0 means you're spending at exactly the sustainable rate, >1.0 means you'll exhaust it before the window ends."
      layouts_json = jsonencode({
        sm = {
          h      = 1
          i      = "1"
          w      = 12
          x      = 0
          y      = 5
          minH   = 1
          minW   = 1
          moved  = false
          static = false
        }
      })
    },
    {
      insight_id = posthog_insight.slo["alerts_us"].id
      layouts_json = jsonencode({
        sm = {
          h      = 5
          i      = "6372084"
          w      = 6
          x      = 0
          y      = 6
          minH   = 1
          minW   = 1
          moved  = false
          static = false
        }
      })
    },
    {
      insight_id = posthog_insight.slo["alerts_timeliness_us"].id
      layouts_json = jsonencode({
        sm = {
          h      = 5
          i      = "6371880"
          w      = 6
          x      = 6
          y      = 6
          minH   = 1
          minW   = 1
          moved  = false
          static = false
        }
      })
    },
    {
      insight_id = posthog_insight.slo["exports_us"].id
      layouts_json = jsonencode({
        sm = {
          h      = 5
          i      = "6371881"
          w      = 6
          x      = 0
          y      = 11
          minH   = 1
          minW   = 1
          moved  = false
          static = false
        }
      })
    },
    {
      insight_id = posthog_insight.slo["exports_eu"].id
      layouts_json = jsonencode({
        sm = {
          h      = 5
          i      = "6371877"
          w      = 6
          x      = 6
          y      = 11
          minH   = 1
          minW   = 1
          moved  = false
          static = false
        }
      })
    },
    {
      insight_id = posthog_insight.slo["cohorts_us"].id
      layouts_json = jsonencode({
        sm = {
          h      = 5
          i      = "6371878"
          w      = 6
          x      = 0
          y      = 16
          minH   = 1
          minW   = 1
          moved  = false
          static = false
        }
      })
    },
    {
      insight_id = posthog_insight.slo["cohorts_eu"].id
      layouts_json = jsonencode({
        sm = {
          h      = 5
          i      = "6371879"
          w      = 6
          x      = 6
          y      = 16
          minH   = 1
          minW   = 1
          moved  = false
          static = false
        }
      })
    },
    {
      insight_id = posthog_insight.slo["subscriptions_us"].id
      layouts_json = jsonencode({
        sm = {
          h      = 5
          i      = "subscriptions_us"
          w      = 6
          x      = 0
          y      = 21
          minH   = 1
          minW   = 1
          moved  = false
          static = false
        }
      })
    },
    {
      insight_id = posthog_insight.slo["subscriptions_eu"].id
      layouts_json = jsonencode({
        sm = {
          h      = 5
          i      = "subscriptions_eu"
          w      = 6
          x      = 6
          y      = 21
          minH   = 1
          minW   = 1
          moved  = false
          static = false
        }
      })
    },
  ]
}
