# Terraform configuration for PostHog dashboard_layout
# Compatible with posthog provider v1.0.6
# Source dashboard_layout ID: 636477

import {
  to = posthog_dashboard_layout.team_analytics_platform_key_metrics
  id = "2/636477"
}

resource "posthog_dashboard_layout" "team_analytics_platform_key_metrics" {
  dashboard_id = posthog_dashboard.team_analytics_platform_key_metrics.id
  tiles = [
    {
      insight_id = posthog_insight.shared_dashboard_stats.id
      layouts_json = jsonencode({
        "sm": {
          "h": 5,
          "i": "4386313",
          "w": 4,
          "x": 0,
          "y": 0,
          "minH": 1,
          "minW": 1,
          "moved": false,
          "static": false
        }
      })
    },
    {
      insight_id = posthog_insight.alert_creation.id
      layouts_json = jsonencode({
        "sm": {
          "h": 5,
          "i": "4386146",
          "w": 4,
          "x": 4,
          "y": 0,
          "minH": 1,
          "minW": 1,
          "moved": false,
          "static": false
        }
      })
    },
    {
      insight_id = posthog_insight.created_subscriptions.id
      color = "white"
      layouts_json = jsonencode({
        "sm": {
          "h": 5,
          "i": "4386493",
          "w": 4,
          "x": 8,
          "y": 0,
          "minH": 1,
          "minW": 1,
          "moved": false,
          "static": false
        }
      })
    },
    {
      insight_id = posthog_insight.dashboards_created_from_template_unique_users.id
      layouts_json = jsonencode({
        "sm": {
          "h": 5,
          "i": "4385815",
          "w": 6,
          "x": 0,
          "y": 5,
          "minH": 1,
          "minW": 1,
          "moved": false,
          "static": false
        }
      })
    },
    {
      insight_id = posthog_insight.dashboard_created_unique_users_by_event_s_source.id
      layouts_json = jsonencode({
        "sm": {
          "h": 5,
          "i": "6241075",
          "w": 6,
          "x": 6,
          "y": 5,
          "minH": 1,
          "minW": 1,
          "moved": false,
          "static": false
        }
      })
    },
    {
      text_body = "## Alerts & Subscriptions 🚨"
      layouts_json = jsonencode({
        "sm": {
          "h": 1,
          "i": "6274566",
          "w": 12,
          "x": 0,
          "y": 10,
          "minH": 1,
          "minW": 1,
          "moved": false,
          "static": false
        }
      })
    },
    {
      insight_id = posthog_insight.export_successes_and_failures["us"].id
      layouts_json = jsonencode({
        "sm": {
          "h": 5,
          "i": "4385817",
          "w": 6,
          "x": 0,
          "y": 11,
          "minH": 1,
          "minW": 1,
          "moved": false,
          "static": false
        }
      })
    },
    {
      insight_id = posthog_insight.export_successes_and_failures["eu"].id
      layouts_json = jsonencode({
        "sm": {
          "h": 5,
          "i": "4704520",
          "w": 6,
          "x": 6,
          "y": 11,
          "minH": 1,
          "minW": 1,
          "moved": false,
          "static": false
        }
      })
    },
    {
      insight_id = posthog_insight.alert_failures_by_exception_type_aggregated.id
      layouts_json = jsonencode({
        "sm": {
          "h": 5,
          "i": "6157400",
          "w": 12,
          "x": 0,
          "y": 16,
          "minH": 1,
          "minW": 1,
          "moved": false,
          "static": false
        }
      })
    },
    {
      text_body = "## Terraform 🛠️"
      layouts_json = jsonencode({
        "sm": {
          "h": 1,
          "i": "6274570",
          "w": 12,
          "x": 0,
          "y": 21,
          "minH": 1,
          "minW": 1,
          "moved": false,
          "static": false
        }
      })
    },
    {
      insight_id = posthog_insight.api_calls_originating_from_our_terraform_provider.id
      layouts_json = jsonencode({
        "sm": {
          "h": 3,
          "i": "4788951",
          "w": 12,
          "x": 0,
          "y": 22,
          "minH": 1,
          "minW": 1,
          "moved": false,
          "static": false
        }
      })
    },
    {
      insight_id = posthog_insight.usage_by_role.id
      layouts_json = jsonencode({
        "sm": {
          "h": 5,
          "i": "3202514",
          "w": 12,
          "x": 0,
          "y": 25,
          "minH": 1,
          "minW": 1,
          "moved": false,
          "static": false
        }
      })
    },
  ]
}
