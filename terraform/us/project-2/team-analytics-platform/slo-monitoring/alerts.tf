locals {
  billing_slo_operation_keys = ["billing_status", "usage_report_ingest"]
  billing_slo_operation_regions = {
    for key, operation in local.slo_operation_regions :
    key => operation if contains(local.billing_slo_operation_keys, operation.operation)
  }

  # A 14.4x burn for one hour consumes roughly 2% of a 28-day error budget.
  billing_slo_fast_burn_threshold = 14.4
}

# PostHog alerts currently require a TrendsQuery, while the dashboard burn-rate
# insights use HogQL to correlate started/completed events. This alert-only insight
# uses the same started-minus-successful-completed availability calculation over
# hourly buckets. These operations complete within an hour, so the bucket boundary
# does not materially change the signal.
resource "posthog_insight" "billing_slo_fast_burn" {
  for_each = local.billing_slo_operation_regions

  name        = "SLO alert: 1h burn rate - ${each.value.name}${each.value.region_count > 1 ? " — ${each.value.region}" : ""}"
  description = "Fast-burn alert source for the ${each.value.slo}% availability objective. Alert threshold: ${local.billing_slo_fast_burn_threshold}x the sustainable error-budget burn rate."
  query_json = jsonencode({
    kind = "InsightVizNode"
    source = {
      kind = "TrendsQuery"
      series = [
        {
          kind        = "EventsNode"
          event       = "slo_operation_started"
          math        = "total"
          custom_name = "Started"
          properties = [
            {
              key      = "operation"
              type     = "event"
              value    = [each.value.operation]
              operator = "exact"
            },
            {
              key      = "region"
              type     = "event"
              value    = [each.value.region]
              operator = "exact"
            }
          ]
        },
        {
          kind        = "EventsNode"
          event       = "slo_operation_completed"
          math        = "total"
          custom_name = "Successful completions"
          properties = [
            {
              key      = "operation"
              type     = "event"
              value    = [each.value.operation]
              operator = "exact"
            },
            {
              key      = "region"
              type     = "event"
              value    = [each.value.region]
              operator = "exact"
            },
            {
              key      = "outcome"
              type     = "event"
              value    = ["success"]
              operator = "exact"
            }
          ]
        }
      ]
      version  = 2
      interval = "hour"
      dateRange = {
        date_from = "-24h"
      }
      trendsFilter = {
        display                 = "ActionsLineGraph"
        decimalPlaces           = 2
        showLegend              = true
        showAlertThresholdLines = true
        formulaNodes = [{
          formula     = "(A-B)/A/${format("%.8f", (100 - each.value.slo) / 100)}"
          custom_name = "1h burn rate"
        }]
      }
      filterTestAccounts = false
    }
  })

  tags = ["managed-by:terraform", "slo", "billing"]
}

resource "posthog_alert" "billing_slo_fast_burn" {
  for_each = posthog_insight.billing_slo_fast_burn

  name                   = "Billing SLO fast burn: ${local.billing_slo_operation_regions[each.key].name}${local.billing_slo_operation_regions[each.key].region_count > 1 ? " — ${local.billing_slo_operation_regions[each.key].region}" : ""}"
  enabled                = true
  calculation_interval   = "hourly"
  condition_type         = "absolute_value"
  threshold_type         = "absolute"
  threshold_upper        = local.billing_slo_fast_burn_threshold
  series_index           = 0
  check_ongoing_interval = false
  insight                = each.value.id
  subscribed_users       = var.analytics_platform_alert_subscribed_user_ids
}

resource "posthog_hog_function" "billing_slo_slack_notification" {
  for_each = posthog_alert.billing_slo_fast_burn

  name        = "Post Billing SLO alert to Slack"
  description = "Post a Billing SLO fast-burn alert to #team-billing"
  type        = "internal_destination"
  enabled     = true
  hog         = "let res := fetch('https://slack.com/api/chat.postMessage', {\n  'body': {\n    'channel': inputs.channel,\n    'icon_emoji': inputs.icon_emoji,\n    'username': inputs.username,\n    'blocks': inputs.blocks,\n    'text': inputs.text\n  },\n  'method': 'POST',\n  'headers': {\n    'Authorization': f'Bearer {inputs.slack_workspace.access_token}',\n    'Content-Type': 'application/json'\n  }\n});\n\nif (res.status != 200 or res.body.ok == false) {\n  throw Error(f'Failed to post message to Slack: {res.status}: {res.body}');\n}"

  inputs_json = jsonencode({
    text = {
      value      = "Billing SLO alert triggered: {event.properties.insight_name}"
      templating = "hog"
    }
    blocks = {
      value = [
        {
          text = {
            text = "Billing SLO alert '{event.properties.alert_name}' is firing"
            type = "plain_text"
          }
          type = "header"
        },
        {
          text = { text = "{event.properties.breaches}", type = "plain_text" }
          type = "section"
        },
        {
          type     = "context"
          elements = [{ text = "Project: <{project.url}|{project.name}>", type = "mrkdwn" }]
        },
        { type = "divider" },
        {
          type = "actions"
          elements = [
            {
              url  = "{project.url}/insights/{event.properties.insight_id}"
              text = { text = "View insight", type = "plain_text" }
              type = "button"
            },
            {
              url  = "{project.url}/insights/{event.properties.insight_id}/alerts?alert_id={event.properties.alert_id}"
              text = { text = "View alert", type = "plain_text" }
              type = "button"
            }
          ]
        }
      ]
      templating = "hog"
    }
    channel         = { value = var.billing_slack_channel_id, templating = "hog" }
    username        = { value = "Billing SLO monitor", templating = "hog" }
    icon_emoji      = { value = ":hogzilla:", templating = "hog" }
    slack_workspace = { value = var.analytics_platform_slack_workspace_id, templating = "hog" }
  })

  filters_json = jsonencode({
    source = "events"
    events = [{ id = "$insight_alert_firing", type = "events" }]
    properties = [{
      key      = "alert_id"
      type     = "event"
      value    = each.value.id
      operator = "exact"
    }]
  })

  template_id = "template-slack"
  icon_url    = "/static/services/slack.png"
}
