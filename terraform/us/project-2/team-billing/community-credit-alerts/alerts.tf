# =============================================================================
# Community credit claim failure alert
# =============================================================================
#
# Posts every $exception from a community credit claim to Slack. The
# #billing-error-feed only posts new or reopened error tracking issues, so
# repeat failures of the same issue are silent there.
#
# Billing sets campaign_slug on the claim endpoint exception and on the
# "Community credit was not applied after coupon claim." exception. See
# notes/community-credits-runbook.md in PostHog/billing for how to re-grant.
#
# For more information, see:
#   https://registry.terraform.io/providers/PostHog/posthog/latest/docs/resources/hog_function
# =============================================================================

locals {
  mentions = join(" ", [for id in var.billing_alert_mention_slack_user_ids : "<@${id}>"])

  # Anyone holding project 2's public key can send an event that passes the filter below.
  # Escaping every event value stops such an event from adding links or mentions to the post.
  escape = "replaceAll(replaceAll(replaceAll(toString(%s ?? ''), '&', '&amp;'), '<', '&lt;'), '>', '&gt;')"

  # Slack rejects a section over 3,000 characters, so the exception text is cut short.
  exception_type = "substring(${format(local.escape, "event.properties.$exception_types[1]")}, 1, 200)"
  message        = "substring(${format(local.escape, "event.properties.$exception_values[1]")}, 1, 2700)"
  details        = "substring(${format(local.escape, "f'Coupon: {event.properties.coupon_id} | Credit: {event.properties.credit_id} | Customer: {event.properties.customer_id} | Organization: {event.properties.organization_id}'")}, 1, 3000)"
  issue_url      = "{project.url}/error_tracking/{encodeURLComponent(toString(event.properties.$exception_issue_id ?? ''))}"
}

resource "posthog_hog_function" "community_credit_claim_failure" {
  name        = "Community credit claim failure to Slack"
  description = "Post to Slack on every $exception with campaign_slug = community"
  type        = "destination"
  enabled     = true
  hog         = "let res := fetch('https://slack.com/api/chat.postMessage', {\n  'body': {\n    'channel': inputs.channel,\n    'icon_emoji': inputs.icon_emoji,\n    'username': inputs.username,\n    'blocks': inputs.blocks,\n    'text': inputs.text\n  },\n  'method': 'POST',\n  'headers': {\n    'Authorization': f'Bearer {inputs.slack_workspace.access_token}',\n    'Content-Type': 'application/json'\n  }\n});\n\nif (res.status != 200 or res.body.ok == false) {\n  throw Error(f'Failed to post message to Slack: {res.status}: {res.body}');\n}"

  inputs_json = jsonencode({
    # Slack shows this fallback text in notifications and can't set verbatim on it, so it carries no event values.
    "text" = {
      "value"      = "${local.mentions} Community credit claim failed"
      "templating" = "hog"
    }
    "blocks" = {
      "value" = [
        {
          "text" = { "text" = "Community credit claim failed", "type" = "plain_text" }
          "type" = "header"
        },
        {
          "text" = {
            "text"     = "${local.mentions} *{${local.exception_type}}*: {${local.message}}"
            "type"     = "mrkdwn"
            "verbatim" = true
          }
          "type" = "section"
        },
        {
          "type" = "context"
          "elements" = [{
            "text"     = "{${local.details}}"
            "type"     = "mrkdwn"
            "verbatim" = true
          }]
        },
        { "type" = "divider" },
        {
          "type" = "actions"
          "elements" = [{
            "url"  = local.issue_url
            "text" = { "text" = "View issue", "type" = "plain_text" }
            "type" = "button"
          }]
        }
      ]
      "templating" = "hog"
    }
    "channel"         = { "value" = var.billing_slack_channel_id, "templating" = "hog" }
    "username"        = { "value" = "Community credits", "templating" = "hog" }
    "icon_emoji"      = { "value" = ":hogzilla:", "templating" = "hog" }
    "slack_workspace" = { "value" = var.billing_slack_workspace_id, "templating" = "hog" }
  })

  filters_json = jsonencode({
    "source" = "events"
    "events" = [{ "id" = "$exception", "type" = "events" }]
    "properties" = [{
      "key"      = "campaign_slug"
      "type"     = "event"
      "value"    = ["community"]
      "operator" = "exact"
    }]
  })

  template_id = "template-slack"
  icon_url    = "/static/services/slack.png"
}
