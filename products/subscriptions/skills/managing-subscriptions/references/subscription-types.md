# Subscription types

Select exactly one resource type at creation.
The API derives `resource_type` from the populated field.
It rejects a subscription that combines resource fields.

| Resource type | Source | Destinations | AI behavior | Type-specific options |
| --- | --- | --- | --- | --- |
| `insight` | One saved insight | Email, Slack, Teams | Optional AI summary | No dashboard tile selection |
| `dashboard` | 1 through 10 selected tiles | Email, Slack, Teams | Optional AI summary | Tile selection and Slack image layout |
| `ai_prompt` | One free-text prompt | Email, Slack, Teams | AI report uses billable model calls | Analysis window and report display options |

## Insight snapshot

Set `insight` to the numeric insight ID.
Use `posthog:insight-get` when the user supplied a short ID or insight URL.

The caller needs viewer access to the insight.
The insight must belong to the current project.

An insight subscription sends the saved insight snapshot.
It does not accept `dashboard_export_insights` or `ai_prompt_config`.

## Dashboard snapshot

Set `dashboard` to the numeric dashboard ID.
Set `dashboard_export_insights` to 1 through 10 insight IDs from that dashboard.

Use `posthog:dashboard-get` to read the tiles.
Ask the user which tiles to include.
Do not select the first tiles without approval.

Each selected insight must meet these requirements:

- It belongs to the current project.
- It is not deleted.
- It is a tile on the selected dashboard.
- The caller has viewer access to it.

## AI prompt report

Set `prompt` to nonempty text with 4,000 characters or fewer.
Do not set `insight` or `dashboard`.

Use `creating-ai-subscription` for the complete creation workflow.
Use this type when the analysis is the product.
Prefer a saved snapshot when an insight or dashboard already answers the request.

The AI planner creates HogQL and writes a report.
The first successful delivery freezes its query plan for later runs.
A prompt change clears the frozen plan.
Enabling chart images also clears a plan that was frozen without images.

### Analysis windows

Set `ai_prompt_config.window.mode` to one of these values:

| Mode | Result |
| --- | --- |
| `since_last_sent` | Analyze data since the last successful scheduled delivery |
| `last_n_days` | Analyze a trailing period from 1 through 365 days |
| `days_ago_range` | Analyze an explicit range within the last 365 days |

Manual and test deliveries do not move the `since_last_sent` anchor.

For `last_n_days`, set `start_days_ago` from 1 through 365.
For `days_ago_range`, also set `end_days_ago` from 0 through 365.
`end_days_ago` must be less than `start_days_ago`.

### Prompt report display options

Set these optional fields in `delivery_config`:

- `include_images`: Include generated chart images. The default is `true`.
- `include_feedback`: Include report feedback links. The default is `true`.
- `include_manage_link`: Include a subscription management link. The default is `true`.
- `include_posthog_hint`: Include PostHog guidance in Slack. The default is `true`.

`include_posthog_hint` does not apply to email or Teams.

## AI summary on a saved snapshot

Insight and dashboard subscriptions can attach an AI summary.
Ask for approval before you enable it.

- Set `summary_enabled: true` to enable the summary.
- Set `summary_prompt_guide` to optional guidance with 500 characters or fewer.
- Do not use these fields for an AI prompt report.

The snapshot remains the source for exact chart results.
The model-written summary can contain an incorrect number.

If AI credits run out, PostHog skips the summary and still sends the snapshot.

## Source changes after creation

A dashboard subscription stores selected insight IDs.
It does not automatically select a replacement tile after a dashboard edit.

Before a dashboard owner removes, replaces, or deletes tiles, list its subscriptions.
After the edit, update each affected `dashboard_export_insights` selection.

Delivery excludes deleted dashboard tiles.
An empty effective selection can produce a delivery with no useful snapshot.

A hard deletion of the source insight or dashboard also deletes its subscription and delivery history.
Use pause or soft deletion when the user needs to preserve subscription history.
