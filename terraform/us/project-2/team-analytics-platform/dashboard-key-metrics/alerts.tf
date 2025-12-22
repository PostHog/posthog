# =============================================================================
# PostHog Alerts Configuration
# =============================================================================
#
# This file demonstrates how to configure PostHog alerts with Slack notifications
# using the PostHog Terraform provider.
#
# Prerequisites:
#   - Set required variables (see variables.tf)
#   - Configure your Slack integration in PostHog
#
# For more information, see:
#   https://registry.terraform.io/providers/PostHog/posthog/latest/docs/resources/alert
# =============================================================================

# Terraform configuration for PostHog alert
# Compatible with posthog provider v1.0
# Source alert ID: 019a972a-2df1-0000-4b6a-8f54b42bbbb3
import {
  to = posthog_alert.decrease_in_success_rate_for_exports
  id = "019a972a-2df1-0000-4b6a-8f54b42bbbb3"
}

resource "posthog_alert" "decrease_in_success_rate_for_exports" {
  name = "Decrease in success rate for exports"
  enabled = true
  calculation_interval = "hourly"
  condition_type = "absolute_value"
  threshold_type = "absolute"
  threshold_lower = 0.97
  series_index = 0
  check_ongoing_interval = false
  insight = posthog_insight.export_successes_and_failures_us.id
  subscribed_users = var.analytics_platform_alert_subscribed_user_ids
}

# Terraform configuration for PostHog hog_function
# Compatible with posthog provider v1.0
# Source hog_function ID: 019a972e-cb45-0000-fbfe-a9c0e26b6547
import {
  to = posthog_hog_function.post_to_slack_on_insight_alert_firing
  id = "019a972e-cb45-0000-fbfe-a9c0e26b6547"
}

resource "posthog_hog_function" "post_to_slack_on_insight_alert_firing" {
  name = "Post to Slack on insight alert firing"
  description = "Post to a Slack channel when this insight alert fires"
  type = "internal_destination"
  enabled = true
  hog = "let res := fetch('https://slack.com/api/chat.postMessage', {\n  'body': {\n    'channel': inputs.channel,\n    'icon_emoji': inputs.icon_emoji,\n    'username': inputs.username,\n    'blocks': inputs.blocks,\n    'text': inputs.text\n  },\n  'method': 'POST',\n  'headers': {\n    'Authorization': f'Bearer {inputs.slack_workspace.access_token}',\n    'Content-Type': 'application/json'\n  }\n});\n\nif (res.status != 200 or res.body.ok == false) {\n  throw Error(f'Failed to post message to Slack: {res.status}: {res.body}');\n}"
  inputs_json = jsonencode({
    "text": {
      "value": "Alert triggered: {event.properties.insight_name}",
      "templating": "hog"
    },
    "blocks": {
      "value": [
        {
          "text": {
            "text": "Alert '{event.properties.alert_name}' firing for insight '{event.properties.insight_name}'",
            "type": "plain_text"
          },
          "type": "header"
        },
        {
          "text": {
            "text": "{event.properties.breaches}",
            "type": "plain_text"
          },
          "type": "section"
        },
        {
          "type": "context",
          "elements": [
            {
              "text": "Project: <{project.url}|{project.name}>",
              "type": "mrkdwn"
            }
          ]
        },
        {
          "type": "divider"
        },
        {
          "type": "actions",
          "elements": [
            {
              "url": "{project.url}/insights/{event.properties.insight_id}",
              "text": {
                "text": "View Insight",
                "type": "plain_text"
              },
              "type": "button"
            },
            {
              "url": "{project.url}/insights/{event.properties.insight_id}/alerts?alert_id={event.properties.alert_id}",
              "text": {
                "text": "View Alert",
                "type": "plain_text"
              },
              "type": "button"
            }
          ]
        }
      ],
      "templating": "hog"
    },
    "channel": {
      "value": var.analytics_platform_slack_channel_id,
      "templating": "hog"
    },
    "username": {
      "value": "Export-monitor",
      "templating": "hog"
    },
    "icon_emoji": {
      "value": ":hogzilla:",
      "templating": "hog"
    },
    "slack_workspace": {
      "value": var.analytics_platform_slack_workspace_id,
      "templating": "hog"
    }
  })
  filters_json = jsonencode({
    "source": "events",
    "events": [
      {
        "id": "$insight_alert_firing",
        "type": "events"
      }
    ],
    "properties": [
      {
        "key": "alert_id",
        "type": "event",
        "value": posthog_alert.decrease_in_success_rate_for_exports.id,
        "operator": "exact"
      }
    ]
  })
  template_id = "template-slack"
  icon_url = "/static/services/slack.png"
}
