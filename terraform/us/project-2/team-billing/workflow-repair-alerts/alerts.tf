# Project 2 accepts public events. Use plain text for their properties and build
# the operator link from encoded path components on the Temporal Cloud host.
locals {
  workflow_url = "https://cloud.temporal.io/namespaces/{encodeURLComponent(toString(event.properties.namespace))}/workflows/{encodeURLComponent(toString(event.properties.workflow_id))}/{encodeURLComponent(toString(event.properties.run_id))}/history"
}

resource "posthog_hog_function" "spine_repair_required" {
  name        = "billing workflow repair alerts"
  description = "Notify billing when a workflow saves a repair report and waits for an operator."
  type        = "destination"
  enabled     = true
  template_id = "template-slack"
  icon_url    = "/static/services/slack.png"

  hog = <<-HOG
    let res := fetch('https://slack.com/api/chat.postMessage', {
      'method': 'POST',
      'headers': {'Authorization': f'Bearer {inputs.slack_workspace.access_token}', 'Content-Type': 'application/json'},
      'body': {'channel': inputs.channel, 'blocks': inputs.blocks, 'text': inputs.text}
    });
    if (res.status != 200 or res.body.ok == false) {
      throw Error(f'Failed to post repair notification: {res.status}: {res.body}');
    }
  HOG

  inputs_json = jsonencode({
    text            = { value = "A billing workflow needs repair", templating = "hog" }
    channel         = { value = var.billing_slack_channel_id, templating = "hog" }
    slack_workspace = { value = var.billing_slack_workspace_id, templating = "hog" }
    blocks = {
      templating = "hog"
      value = [
        {
          type = "section"
          text = {
            type = "plain_text"
            text = "{substring(f'Billing repair #{event.properties.repair_id}\nAttempt: {event.properties.attempt ?? 'Unknown'}\nBilling customer: {event.properties.customer_id ?? 'Unknown'}\nMachine: {event.properties.machine}\nWorkflow ID: {event.properties.workflow_id}\nWorkflow key: {event.properties.workflow_key ?? 'Unknown'}\nSource fact: {event.properties.source_fact_id} ({event.properties.source_fact_type ?? 'Unknown'})\nReason: {event.properties.reason}', 1, 3000)}"
          }
        },
        {
          type = "actions"
          elements = [{
            type = "button"
            text = { type = "plain_text", text = "View workflow" }
            url  = local.workflow_url
          }]
        }
      ]
    }
  })

  filters_json = jsonencode({
    source = "events"
    events = [{ id = "billing spine repair required", type = "events" }]
    properties = [
      { key = "repo_identifier", type = "event", value = ["billing"], operator = "exact" },
      { key = "billing_site_url", type = "event", value = ["https://billing.posthog.com"], operator = "exact" }
    ]
  })
}
