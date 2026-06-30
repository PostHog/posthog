# Block-kit and message body templates

Canonical message body shapes for each event × integration. Copy verbatim — these match the in-product
alert wizard, so agent-created and UI-created alerts produce identical notifications.

The three placeholders inside `inputs` that you must fill at create time are:

- `slack_workspace.value` — the integer integration id from `posthog:integrations-list` (Slack only).
- `channel.value` — Slack channel id like `C0123ABC` (preferred) or `#name`.
- `url.value` — webhook destination URL (webhook integrations only).

Everything else in the templates below is a HogQL template expression that will be evaluated at fire
time against the live event — leave the curly-braced segments as-is.

## `$error_tracking_issue_created`

### Slack — `template-slack`

````json
{
  "type": "internal_destination",
  "template_id": "template-slack",
  "name": "Issue created · #<channel> (auto)",
  "enabled": true,
  "filters": {
    "events": [{ "id": "$error_tracking_issue_created", "type": "events" }]
  },
  "inputs": {
    "slack_workspace": { "value": <slack_integration_id_int> },
    "channel": { "value": "<channel_id>" },
    "text": { "value": "New issue created: {event.properties.name}" },
    "blocks": {
      "value": [
        { "type": "header", "text": { "type": "plain_text", "text": "🔴 {event.properties.name}" } },
        { "type": "section", "text": { "type": "plain_text", "text": "New issue created" } },
        { "type": "section", "text": { "type": "mrkdwn", "text": "```{substring(event.properties.description, 1, 150)}```" } },
        {
          "type": "context",
          "elements": [
            { "type": "plain_text", "text": "Status: {event.properties.status}" },
            { "type": "mrkdwn", "text": "Project: <{project.url}|{project.name}>" },
            { "type": "mrkdwn", "text": "Alert: <{source.url}|{source.name}>" }
          ]
        },
        { "type": "divider" },
        {
          "type": "actions",
          "elements": [
            {
              "type": "button",
              "text": { "type": "plain_text", "text": "View Issue" },
              "url": "{project.url}/error_tracking/{event.distinct_id}?fingerprint={event.properties.fingerprint}&timestamp={event.properties.exception_timestamp}&utm_source=alert&utm_campaign=error_tracking_alert&utm_medium=slack"
            }
          ]
        }
      ]
    }
  }
}
````

### Webhook — `template-webhook`

```json
{
  "type": "internal_destination",
  "template_id": "template-webhook",
  "name": "Issue created · <host> (auto)",
  "enabled": true,
  "filters": {
    "events": [{ "id": "$error_tracking_issue_created", "type": "events" }]
  },
  "inputs": {
    "url": { "value": "https://example.com/hooks/posthog-error-tracking" }
  }
}
```

### Discord — `template-discord`

```json
"inputs": {
  "content": {
    "value": "**🔴 {event.properties.name} created:** {event.properties.description}"
  }
}
```

### Microsoft Teams — `template-microsoft-teams`

```json
"inputs": {
  "text": {
    "value": "**🔴 {event.properties.name} created:** {event.properties.description} (View in [PostHog]({project.url}/error_tracking/{event.distinct_id}?fingerprint={event.properties.fingerprint}&timestamp={event.properties.exception_timestamp}&utm_source=alert&utm_campaign=error_tracking_alert&utm_medium=microsoft_teams))"
  }
}
```

### Linear / GitHub / GitLab

These integrations file a tracking issue rather than post a message. Use the same `inputs` shape across
all three:

```json
"inputs": {
  "title": { "value": "{event.properties.name}" },
  "description": { "value": "{event.properties.description}" },
  "posthog_issue_id": { "value": "{event.distinct_id}" }
}
```

## `$error_tracking_issue_reopened`

### Slack — `template-slack`

Same as `_created`, with the header swapped to `🔄` and the section text to "Issue reopened":

````json
"blocks": {
  "value": [
    { "type": "header", "text": { "type": "plain_text", "text": "🔄 {event.properties.name}" } },
    { "type": "section", "text": { "type": "plain_text", "text": "Issue reopened" } },
    { "type": "section", "text": { "type": "mrkdwn", "text": "```{substring(event.properties.description, 1, 150)}```" } },
    {
      "type": "context",
      "elements": [
        { "type": "plain_text", "text": "Status: {event.properties.status}" },
        { "type": "mrkdwn", "text": "Project: <{project.url}|{project.name}>" },
        { "type": "mrkdwn", "text": "Alert: <{source.url}|{source.name}>" }
      ]
    },
    { "type": "divider" },
    {
      "type": "actions",
      "elements": [
        {
          "type": "button",
          "text": { "type": "plain_text", "text": "View Issue" },
          "url": "{project.url}/error_tracking/{event.distinct_id}?fingerprint={event.properties.fingerprint}&timestamp={event.properties.exception_timestamp}&utm_source=alert&utm_campaign=error_tracking_alert&utm_medium=slack"
        }
      ]
    }
  ]
},
"text": { "value": "Issue reopened: {event.properties.name}" }
````

### Discord / Microsoft Teams

Use the same shape as `_created`, swap `🔴` → `🔄` and "created" → "reopened" in the text body.

## `$error_tracking_issue_spiking`

### Slack — `template-slack`

````json
"blocks": {
  "value": [
    { "type": "header", "text": { "type": "plain_text", "text": "📈 Issue spiking" } },
    { "type": "section", "text": { "type": "mrkdwn", "text": "```{event.properties.name}: {substring(event.properties.description, 1, 1000)}```" } },
    {
      "type": "context",
      "elements": [
        {
          "type": "plain_text",
          "text": "Exceptions in last 5 minutes: {event.properties.current_bucket_value} ({event.properties.computed_baseline > 0 ? concat(round(event.properties.current_bucket_value / event.properties.computed_baseline), 'x over baseline') : 'no baseline yet'})"
        },
        { "type": "mrkdwn", "text": "Project: <{project.url}|{project.name}>" },
        { "type": "mrkdwn", "text": "Alert: <{source.url}|{source.name}>" }
      ]
    },
    { "type": "divider" },
    {
      "type": "actions",
      "elements": [
        {
          "type": "button",
          "text": { "type": "plain_text", "text": "View Issue" },
          "url": "{project.url}/error_tracking/{event.distinct_id}?utm_source=alert&utm_campaign=error_tracking_alert&utm_medium=slack"
        }
      ]
    }
  ]
},
"text": { "value": "Issue spiking: {event.properties.name}" }
````

The `computed_baseline > 0 ? ... : 'no baseline yet'` guard handles the first spike of the project's
lifetime, when the detector has not built up enough history to compute a baseline. Without the guard you
end up with `0x over baseline` in the message, which is wrong.

### Discord — `template-discord`

````json
"inputs": {
  "content": {
    "value": "**📈 Issue spiking**\n\n```\n{event.properties.name}: {substring(event.properties.description, 1, 1000)}\n```\n**Exceptions in last 5 minutes:** {event.properties.current_bucket_value} ({event.properties.computed_baseline > 0 ? concat(round(event.properties.current_bucket_value / event.properties.computed_baseline), 'x over baseline') : 'no baseline yet'})\n**Project:** [{project.name}]({project.url})\n**Alert:** [{source.name}]({source.url})\n\n[View issue]({project.url}/error_tracking/{event.distinct_id}?utm_source=alert&utm_campaign=error_tracking_alert&utm_medium=discord)"
  }
}
````

### Microsoft Teams — `template-microsoft-teams`

```json
"inputs": {
  "text": {
    "value": "**📈 Issue spiking: {event.properties.name}:** {event.properties.description}\n**Exceptions in last 5 minutes:** {event.properties.current_bucket_value} ({event.properties.computed_baseline > 0 ? concat(round(event.properties.current_bucket_value / event.properties.computed_baseline), 'x over baseline') : 'no baseline yet'}) (View in [PostHog]({project.url}/error_tracking/{event.distinct_id}?utm_source=alert&utm_campaign=error_tracking_alert&utm_medium=microsoft_teams))"
  }
}
```
