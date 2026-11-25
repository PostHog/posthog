# Connector configuration

## Bind a watch to a PostHog workflow

For a `posthog` or `mcp` connection, put the existing PostHog workflow ID in the watch entry's `workflow` field. With a binding, the default `mode` is `push`. Without one it is `pull`. Set `mode` to `push` explicitly for a manually configured workflow whose remote ID the host does not store. The host can inspect `supported_modes(kind, workflow_configured)`. The connector consumes the binding the host supplies. Create the trigger and webhook step in PostHog.

```json
{
  "connection":"analytics",
  "webhook_auth":{"kind":"hmac_sha256","header":"x-workflow-signature"},
  "watches":[{
    "watch":{"id":"00000000-0000-4000-8000-000000000001","connection":"analytics",
             "kind":"insight","key":"signups","label":"Signups"},
    "workflow":"WORKFLOW_ID","mode":"push"
  }]
}
```

This connection accepts workflow deliveries for the configured watch kind and key. Its push watches make no polling requests. A connection with both push and pull watches needs the workflow `secret` and the MCP `token`. A standalone `webhook` connection accepts the workflow preset directly with `auth` and optional `watch` or `watches`.

## Post the workflow observation

Configure the PostHog workflow's webhook step to POST JSON to `/v1/ingest/{connection}` after its trigger matches. This is the same body for insight alerts, event matches and observations from services that feed PostHog.

```json
{
  "topic_hint":"00000000-0000-4000-8000-000000000010",
  "source":{"service":"slack","kind":"channel","key":"C123"},
  "author":"U42",
  "at":"2026-11-21T18:42:12.123Z",
  "text":"The release is ready.",
  "external_id":"workflow-run-178:observation-6",
  "thread_hint":"C123/1470182845.045182",
  "attributes":{"fact":"The release is ready."}
}
```

Use an account-unique `external_id` for each observation and reuse it on retries. `at` is an RFC 3339 timestamp. The endpoint supplies the event's connection. The source kind and key become its kind and channel. Optional `attributes` retains workflow context. The connector also preserves the signed source and optional topic hint there. A topic hint is provenance, and the engine routes using the account's grants and watches. `thread_hint` is optional.

Use a distinct secret for each connection. With `hmac_sha256`, compute the hex HMAC-SHA256 of the exact UTF-8 body and send it in the configured header, optionally prefixed with `sha256=`. For a workflow step that can supply a static header, choose `shared_secret`. The default workflow preset uses `shared_secret` in `x-meep-secret`. The host supplies the credential in the secrets map under `secret`.

After authentication and mapping, `receive_webhook` returns events whose IDs the host has yet to acknowledge. Ingest them through the engine, call `acknowledge_webhook`, then return HTTP 204. A failed ingest stays retryable. A repeated or concurrent delivery uses the same external ID for engine deduplication. File-backed `StoreState` remembers acknowledgments across restarts. When wrapping the store to stage poll commits, delegate both webhook receipt methods to the durable store.

For an existing workflow with a different body shape, supply one `watch` and a `mapping` in place of `preset`. The optional `items` pointer selects an object or array (default is the root). Required JSON pointers `id`, `author`, `text`, and `timestamp` are relative to each item. Set `thread` for a thread hint. For `author` and `thread`, an ordered list supplies fallback pointers. Custom mappings also accept Unix timestamps with up to nine fractional digits.

## Poll PostHog

Set `kind` to `posthog`. Supply `connection`, `watches` and the person’s OAuth access token in the `token` secret. The default streamable HTTP endpoint is `https://mcp.posthog.com/mcp`. Set `mcp_endpoint` for a different deployment. Optional `project` pins that numeric project in the MCP session. Each pull entry contains a Topics `watch` and the options below.

| Watch kind | Options and behavior |
| --- | --- |
| `insight` | Use the insight short ID or numeric ID as the watch key, or set a numeric `resource_id` alongside `watch`. The first numeric result sets the baseline. A change from the preceding poll greater than the absolute `threshold` (default zero) emits an event in either direction. The connector evaluates the saved query and reads the last bucket of the first trends series. Use `result_pointer` relative to the result for another cell. |
| `flag` | Use the flag’s string key or numeric ID. An explicit numeric `resource_id` takes precedence. After the first observation, a change to activation or targeting/rollout filters emits an event. |
| `event` | The watch key is the literal event name. Set positive integer `window_seconds` and `threshold`. Emit when the window count first reaches or exceeds the threshold, including on the initial poll. A count below the threshold arms the watch again. |

Every poll discovers the tools available to the OAuth session. It tries these names in order and reports the expected names if none are available.

| Operation | Accepted advertised names |
| --- | --- |
| Run a saved insight | `insight-query`, `insight_query`, `query-insight` |
| Read a flag by ID | `feature-flag-get-definition`, `feature_flag_get_definition`, `get-feature-flag` |
| Read a flag by key | `feature-flag-get-definition-by-key`, `feature_flag_get_definition_by_key` |
| Count events with HogQL | `execute-sql`, `execute_sql`, `query-run` |

Changes include `old`, `new` and a readable `fact` in `attributes`. Open the same file-backed database on every start. Polls publish checkpoints for the entire account together. Repointing a watch to a different resource starts a new baseline.

## Configure MCP watches

Use `kind = "mcp"`, the connection ID, the person’s PostHog API `origin`, numeric `project`, and real `installation_id`. Supply the OAuth access token as the `token` secret. Each entry in `watches` includes a Topics `watch`, an advertised `tool` name, `arguments`, and a `mapping`. Every poll discovers tools for that installation. A call requires an advertised tool with `approval_state` set to `approved`. Match each template to the tool name, arguments and response shape advertised by the installed server.

**Slack channel history.** For a `channel` watch, use the actual channel ID as the watch key and tool argument. Merge these fields into its watch entry. The first call sends the inclusive poll watermark as Unix seconds in `oldest`. A caller-supplied `arguments.oldest` takes precedence on that call. The connector saves the newest message's original timestamp for the next call and follows Slack's page cursors within each poll.

[Download the slack channel history template](templates/slack-channel-history.json)

**GitHub pull request activity.** For a repository watch, use its owner and name in the arguments. This template reads PRs in most-recently-updated order. It maps each update timestamp to a distinct event for the same PR thread. Set `mapping.items` to the array pointer when the gateway wraps structured results.

[Download the github pull requests template](templates/github-pull-requests.json)
