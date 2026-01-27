# =============================================================================
# PostHog Alerts Configuration
# =============================================================================
#
# This file configures PostHog alerts with Slack notifications using for_each
# to avoid duplication across regions and alert types.
#
# Prerequisites:
#   - Set required variables (see variables.tf)
#   - Configure your Slack integration in PostHog
#
# For more information, see:
#   https://registry.terraform.io/providers/PostHog/posthog/latest/docs/resources/alert
# =============================================================================

locals {
  regions = {
    us = posthog_insight.export_successes_and_failures["us"]
    eu = posthog_insight.export_successes_and_failures["eu"]
  }

  # Alert configurations (shared across regions)
  alert_configs = {
    decrease_in_success_rate = {
      name            = "Decrease in success rate for exports"
      threshold_lower = 0.99
      threshold_upper = null
      series_index    = 0
    }
    timeout_spike = {
      name            = "Timeout spike"
      threshold_lower = null
      threshold_upper = 0.03
      series_index    = 5
    }
    system_error_spike = {
      name            = "System error spike"
      threshold_lower = null
      threshold_upper = 0.03
      series_index    = 4
    }
    user_error_spike = {
      name            = "User error spike"
      threshold_lower = null
      threshold_upper = 0.03
      series_index    = 3
    }
    unknown_alert_spike = {
      name            = "Unknown alert spike"
      threshold_lower = null
      threshold_upper = 0.01
      series_index    = 6
    }
  }

  # Flatten: creates keys like "decrease_in_success_rate_us", "decrease_in_success_rate_eu"
  alerts = merge([
    for region_key, insight in local.regions : {
      for alert_key, config in local.alert_configs :
      "${alert_key}_${region_key}" => merge(config, {
        region  = region_key
        insight = insight
      })
    }
  ]...)
}

resource "posthog_alert" "export_alert" {
  for_each = local.alerts

  name                   = "${each.value.name} (${upper(each.value.region)})"
  enabled                = true
  calculation_interval   = "daily"
  condition_type         = "absolute_value"
  threshold_type         = "absolute"
  threshold_lower        = each.value.threshold_lower
  threshold_upper        = each.value.threshold_upper
  series_index           = each.value.series_index
  check_ongoing_interval = false
  insight                = each.value.insight.id
  subscribed_users       = var.analytics_platform_alert_subscribed_user_ids
}

resource "posthog_hog_function" "slack_alert_notification" {
  for_each = posthog_alert.export_alert

  name        = "Post to Slack on insight alert firing"
  description = "Post to a Slack channel when this insight alert fires"
  type        = "internal_destination"
  enabled     = true
  hog         = "let res := fetch('https://slack.com/api/chat.postMessage', {\n  'body': {\n    'channel': inputs.channel,\n    'icon_emoji': inputs.icon_emoji,\n    'username': inputs.username,\n    'blocks': inputs.blocks,\n    'text': inputs.text\n  },\n  'method': 'POST',\n  'headers': {\n    'Authorization': f'Bearer {inputs.slack_workspace.access_token}',\n    'Content-Type': 'application/json'\n  }\n});\n\nif (res.status != 200 or res.body.ok == false) {\n  throw Error(f'Failed to post message to Slack: {res.status}: {res.body}');\n}"

  inputs_json = jsonencode({
    "text" = {
      "value"      = "Alert triggered: {event.properties.insight_name}"
      "templating" = "hog"
    }
    "blocks" = {
      "value" = [
        {
          "text" = {
            "text" = "Alert '{event.properties.alert_name}' firing for insight '{event.properties.insight_name}'"
            "type" = "plain_text"
          }
          "type" = "header"
        },
        {
          "text" = { "text" = "{event.properties.breaches}", "type" = "plain_text" }
          "type" = "section"
        },
        {
          "type"     = "context"
          "elements" = [{ "text" = "Project: <{project.url}|{project.name}>", "type" = "mrkdwn" }]
        },
        { "type" = "divider" },
        {
          "type" = "actions"
          "elements" = [
            {
              "url"  = "{project.url}/insights/{event.properties.insight_id}"
              "text" = { "text" = "View Insight", "type" = "plain_text" }
              "type" = "button"
            },
            {
              "url"  = "{project.url}/insights/{event.properties.insight_id}/alerts?alert_id={event.properties.alert_id}"
              "text" = { "text" = "View Alert", "type" = "plain_text" }
              "type" = "button"
            }
          ]
        }
      ]
      "templating" = "hog"
    }
    "channel"         = { "value" = var.analytics_platform_slack_channel_id, "templating" = "hog" }
    "username"        = { "value" = "Export-monitor", "templating" = "hog" }
    "icon_emoji"      = { "value" = ":hogzilla:", "templating" = "hog" }
    "slack_workspace" = { "value" = var.analytics_platform_slack_workspace_id, "templating" = "hog" }
  })

  filters_json = jsonencode({
    "source" = "events"
    "events" = [{ "id" = "$insight_alert_firing", "type" = "events" }]
    "properties" = [{
      "key"      = "alert_id"
      "type"     = "event"
      "value"    = each.value.id
      "operator" = "exact"
    }]
  })

  template_id = "template-slack"
  icon_url    = "/static/services/slack.png"
}
