# Block-kit and message body templates

Canonical message body shapes for each event × integration. Copy verbatim — these match the in-product
alert wizard, so agent-created and UI-created alerts produce identical notifications.

The three placeholders inside `inputs` that you must fill at create time are:

- `slack_workspace.value` — the integer integration id from `posthog:integrations-list` (Slack only).
- `channel.value` — Slack channel id like `C0123ABC` (preferred) or `#name`.
- `url.value` — webhook destination URL (webhook integrations only).

Everything else in the templates below is a HogQL template expression that will be evaluated at fire
time against the live event — leave the curly-braced segments as-is.

## Contents

- `$error_tracking_issue_created`
- `$error_tracking_issue_reopened`
- `$error_tracking_issue_spiking`

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
              "url": "{project.url}/error-tracking/fingerprint/{encodeURLComponent(event.properties.fingerprint)}?timestamp={event.properties.exception_timestamp}&utm_source=alert&utm_campaign=error_tracking_alert&utm_medium=slack"
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
    "value": "**🔴 {event.properties.name} created:** {event.properties.description}\n\n[View in PostHog]({project.url}/error-tracking/fingerprint/{encodeURLComponent(event.properties.fingerprint)}?timestamp={event.properties.exception_timestamp}&utm_source=alert&utm_campaign=error_tracking_alert&utm_medium=discord)"
  }
}
```

### Microsoft Teams — `template-microsoft-teams`

```json
"inputs": {
  "text": {
    "value": "**🔴 {event.properties.name} created:** {event.properties.description} (View in [PostHog]({project.url}/error-tracking/fingerprint/{encodeURLComponent(event.properties.fingerprint)}?timestamp={event.properties.exception_timestamp}&utm_source=alert&utm_campaign=error_tracking_alert&utm_medium=microsoft_teams))"
  }
}
```

### Linear / GitHub / GitLab

These integrations file a tracking issue rather than post a message. Use the same `inputs` shape across
all three:

````json
"inputs": {
  "title": { "value": "{substring(replaceAll(notEmpty(event.properties.description) ? concat(event.properties.name, ': ', event.properties.description) : event.properties.name, '\\n', ' '), 1, 120)}" },
  "description": { "value": "{notEmpty(event.properties.description) ? concat('```\\n', replaceAll(event.properties.description, '`', '\\''), '\\n```') : ''}\n{notEmpty(trim(concat(event.properties.$browser, ' ', event.properties.$browser_version))) ? concat('\\n- Browser: ', concat('`', replaceAll(replaceAll(replaceAll(trim(concat(event.properties.$browser, ' ', event.properties.$browser_version)), '`', '\\''), '\\n', ' '), '\\r', ' '), '`')) : ''}{notEmpty(trim(concat(event.properties.$os, ' ', event.properties.$os_version))) ? concat('\\n- OS: ', concat('`', replaceAll(replaceAll(replaceAll(trim(concat(event.properties.$os, ' ', event.properties.$os_version)), '`', '\\''), '\\n', ' '), '\\r', ' '), '`')) : ''}{notEmpty(event.properties.$exception_release.version) ? concat('\\n- Release: ', concat('`', replaceAll(replaceAll(replaceAll(event.properties.$exception_release.version, '`', '\\''), '\\n', ' '), '\\r', ' '), '`')) : ''}{notEmpty(event.properties.$session_id) and (empty(event.properties.$recording_status) or has(['active', 'sampled', 'buffering'], event.properties.$recording_status)) ? concat('\\n- Session replay: ', concat(project.url, '/replay/', encodeURLComponent(event.properties.$session_id))) : ''}" },
  "posthog_issue_id": { "value": "{event.distinct_id}" },
  "posthog_issue_url": { "value": "{project.url}/error-tracking/fingerprint/{encodeURLComponent(event.properties.fingerprint)}?timestamp={event.properties.exception_timestamp}&utm_source=alert&utm_campaign=error_tracking_alert&utm_medium=linear" }
}
````

The title reads as the exception type and message, for example `RangeError: Invalid Date`, on one line, cut at 120 characters.
The description is the message, then a Markdown list of the browser, OS, release and a session replay link.
The destination code then adds up to 5 resolved in-app stack frames as a code block, so the inputs do not carry the trace.
Each frame shows only the file name, the line and the function name.
A file name that does not look like a source file, a function name with characters outside an identifier set, or any name that holds a UUID or looks like a key or token, becomes `[redacted]`.
The message sits in a code block and the browser, OS and release values sit in inline code, so client-sent text cannot render links, images or @mentions.
Do not add the page URL, request data, local variables or source lines to these inputs. Trackers sit outside PostHog's access controls and a repository can be public, so these values can expose tokens and user data.
Each list line is left out when the event has no value for it, and the replay line is left out when replay was not recording.
Keep the list form: GitLab joins plain consecutive lines into one paragraph.
`_spiking` events carry no exception properties, so on them only the message would render.

Set `utm_medium` to the destination (`linear`, `github`, `gitlab`). `posthog_issue_url` is the merge-stable deep link embedded in the external issue; when omitted, the destination falls back to building a link from `posthog_issue_id`.

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
          "url": "{project.url}/error-tracking/fingerprint/{encodeURLComponent(event.properties.fingerprint)}?timestamp={event.properties.exception_timestamp}&utm_source=alert&utm_campaign=error_tracking_alert&utm_medium=slack"
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
          "url": "{project.url}/error-tracking/fingerprint/{encodeURLComponent(event.properties.fingerprint)}?timestamp={event.properties.exception_timestamp}&utm_source=alert&utm_campaign=error_tracking_alert&utm_medium=slack"
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
    "value": "**📈 Issue spiking**\n\n```\n{event.properties.name}: {substring(event.properties.description, 1, 1000)}\n```\n**Exceptions in last 5 minutes:** {event.properties.current_bucket_value} ({event.properties.computed_baseline > 0 ? concat(round(event.properties.current_bucket_value / event.properties.computed_baseline), 'x over baseline') : 'no baseline yet'})\n**Project:** [{project.name}]({project.url})\n**Alert:** [{source.name}]({source.url})\n\n[View issue]({project.url}/error-tracking/fingerprint/{encodeURLComponent(event.properties.fingerprint)}?timestamp={event.properties.exception_timestamp}&utm_source=alert&utm_campaign=error_tracking_alert&utm_medium=discord)"
  }
}
````

### Microsoft Teams — `template-microsoft-teams`

```json
"inputs": {
  "text": {
    "value": "**📈 Issue spiking: {event.properties.name}:** {event.properties.description}\n**Exceptions in last 5 minutes:** {event.properties.current_bucket_value} ({event.properties.computed_baseline > 0 ? concat(round(event.properties.current_bucket_value / event.properties.computed_baseline), 'x over baseline') : 'no baseline yet'}) (View in [PostHog]({project.url}/error-tracking/fingerprint/{encodeURLComponent(event.properties.fingerprint)}?timestamp={event.properties.exception_timestamp}&utm_source=alert&utm_campaign=error_tracking_alert&utm_medium=microsoft_teams))"
  }
}
```
