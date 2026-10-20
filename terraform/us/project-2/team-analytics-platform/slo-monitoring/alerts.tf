resource "posthog_alert" "alert_delivery_slo" {
  for_each = posthog_insight.alert_delivery_failure_rate

  name                   = "Alert notification delivery SLO breach (${each.key})"
  enabled                = true
  calculation_interval   = "daily"
  condition_type         = "absolute_value"
  threshold_type         = "absolute"
  threshold_upper        = 0.0005
  series_index           = 0
  check_ongoing_interval = false
  insight                = each.value.id
  subscribed_users       = var.analytics_platform_alert_subscribed_user_ids
}

resource "posthog_alert" "slo_regression" {
  name                 = "SLO regression: daily burn rate > 3x baseline"
  enabled              = true
  calculation_interval = "daily"
  condition_type       = "absolute_value"
  threshold_type       = "absolute"
  threshold_upper      = 3
  evaluation           = "any_row"
  column               = "regression_ratio"
  label_column         = "operation"
  insight              = posthog_insight.slo_regression.id
  subscribed_users     = var.analytics_platform_alert_subscribed_user_ids
}

resource "posthog_hog_function" "slo_regression_slack" {
  name        = "Post SLO regression alert to #alerts-product-analytics"
  description = "Post to a Slack channel when the SLO regression alert fires"
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
    # #alerts-product-analytics
    "channel"         = { "value" = "C05G937QY1Z", "templating" = "hog" }
    "username"        = { "value" = "SLO-monitor", "templating" = "hog" }
    "icon_emoji"      = { "value" = ":hogzilla:", "templating" = "hog" }
    "slack_workspace" = { "value" = var.analytics_platform_slack_workspace_id, "templating" = "hog" }
  })

  filters_json = jsonencode({
    "source" = "events"
    "events" = [{ "id" = "$insight_alert_firing", "type" = "events" }]
    "properties" = [{
      "key"      = "alert_id"
      "type"     = "event"
      "value"    = posthog_alert.slo_regression.id
      "operator" = "exact"
    }]
  })

  template_id = "template-slack"
  icon_url    = "/static/services/slack.png"
}
