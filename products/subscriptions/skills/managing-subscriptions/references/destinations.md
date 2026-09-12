# Destinations

Subscriptions support `email`, `slack`, and `teams`.
They do not support a generic webhook destination.

## Email

- Set `target_type` to `email`.
- Set `target_value` to comma-separated email addresses.

Email recipients can use an unsubscribe link.
An unsubscribe token expires after 30 days.

One recipient can unsubscribe without stopping delivery to other recipients.
PostHog removes that address from `target_value`.
PostHog soft-deletes the subscription when the last email recipient unsubscribes.

The overall delivery can succeed when at least one recipient succeeds.
The MCP tools do not return per-recipient results.
Ask the user to confirm receipt when every address matters.

## Slack

1. Call `posthog:integrations-list` and find an integration with `kind: slack`.
2. Call `posthog:integrations-channels-retrieve` for that integration.
3. Set `integration_id` to the integration ID.
4. Set `target_value` to `<channel_id>|<channel_name>`.

The integration must belong to the current project.
The API uses the channel ID for delivery.

For dashboard snapshots, `delivery_config.post_all_insights_in_main_message` controls Slack layout.
The default is `false`.
PostHog sends the first image in the main message and the rest in a thread.

Set the option to `true` to send all images in the main message.
This option requires the Slack `files:write` permission.
It does not apply to email or Teams.

## Microsoft Teams

1. Ask the user to add the Workflows app to the target channel.
2. Ask them to select the workflow that posts to a channel after a webhook request.
3. Set `target_type` to `teams`.
4. Set `target_value` to the full HTTPS webhook URL.
5. Omit `integration_id`.

A URL from a different workflow can save but fail to deliver.

The webhook URL is a credential.
Anyone with the URL can post to the channel.
Pass it only as `target_value`.
Never repeat it in a response, error, log, or summary.

The API returns only the webhook host.
The host cannot identify a Teams channel.
It cannot replace the saved URL during an update.

To keep the saved URL, omit `target_value`.
To change it, send a full new webhook URL.
When you change from Teams, send the new destination value in the same update.

## Destination failures

- If Slack is not connected, ask the user to connect it in Project settings > Integrations.
- If Slack cannot post, check channel access and the integration state.
- If Slack cannot upload files, reconnect it with the `files:write` permission.
- If Teams rejects delivery, ask the user to create a new URL with the correct workflow.
- If the user asks for a generic webhook, offer email, Slack, or Microsoft Teams.

PostHog can automatically disable a subscription after a permanent destination failure.
Fix the destination before you resume it.

Destination acceptance does not prove external delivery.
Send an approved test and check its delivery record after destination setup or replacement.
