# =============================================================================
# Partner billing alert
# =============================================================================
#
# Posts every partner billing $exception to Slack. The #billing-error-feed only
# posts new or reopened error tracking issues, so repeat failures of the same
# issue are silent there.
#
# Billing reports these problems with capture_message or capture_exception.
# It sets partner_billing_alert and alert_kind on each event, and payer_id,
# organization_id, organization_ids, customer_count, reason or mismatch when
# it knows them.
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
  message   = "substring(${format(local.escape, "event.properties.$exception_values[1]")}, 1, 2700)"
  details   = "substring(${format(local.escape, "f'Kind: {event.properties.alert_kind}{notEmpty(event.properties.reason) ? f' | Reason: {event.properties.reason}' : ''}{notEmpty(event.properties.mismatch) ? f' | Mismatch: {event.properties.mismatch}' : ''}{event.properties.payer_id != null ? f' | Payer: {event.properties.payer_id}' : ''}{notEmpty(event.properties.organization_id) ? f' | Organization: {event.properties.organization_id}' : ''}{event.properties.customer_count != null ? f' | Customers: {event.properties.customer_count}' : ''}{notEmpty(event.properties.organization_ids) ? concat(' | Organizations: ', substring(arrayStringConcat(event.properties.organization_ids, ', '), 1, 2500)) : ''}'")}, 1, 3000)"
  issue_url = "{project.url}/error_tracking/{encodeURLComponent(toString(event.properties.$exception_issue_id ?? ''))}"
}

resource "posthog_hog_function" "partner_billing_alert" {
  name        = "Partner billing alert to Slack"
  description = "Post to Slack on every $exception with partner_billing_alert = true"
  type        = "destination"
  enabled     = true
  hog         = "let res := fetch('https://slack.com/api/chat.postMessage', {\n  'body': {\n    'channel': inputs.channel,\n    'icon_emoji': inputs.icon_emoji,\n    'username': inputs.username,\n    'blocks': inputs.blocks,\n    'text': inputs.text\n  },\n  'method': 'POST',\n  'headers': {\n    'Authorization': f'Bearer {inputs.slack_workspace.access_token}',\n    'Content-Type': 'application/json'\n  }\n});\n\nif (res.status != 200 or res.body.ok == false) {\n  throw Error(f'Failed to post message to Slack: {res.status}: {res.body}');\n}"

  inputs_json = jsonencode({
    # Slack shows this fallback text in notifications and can't set verbatim on it, so it carries no event values.
    "text" = {
      "value"      = "${local.mentions} Partner billing alert"
      "templating" = "hog"
    }
    "blocks" = {
      "value" = [
        {
          "text" = {
            "text"     = "${local.mentions} {${local.message}}"
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
    "username"        = { "value" = "Partner billing", "templating" = "hog" }
    "icon_emoji"      = { "value" = ":hogzilla:", "templating" = "hog" }
    "slack_workspace" = { "value" = var.billing_slack_workspace_id, "templating" = "hog" }
  })

  filters_json = jsonencode({
    "source" = "events"
    "events" = [{ "id" = "$exception", "type" = "events" }]
    "properties" = [{
      "key"      = "partner_billing_alert"
      "type"     = "event"
      "value"    = ["true"]
      "operator" = "exact"
    }]
  })

  template_id = "template-slack"
  icon_url    = "/static/services/slack.png"
}
