# meep-server

Run the Meep engine on a host that stays online. A new server starts with an empty topic store. This example starts the server and reads its health from a second terminal on the same machine.

```sh
cargo run -p meep-server -- --data-dir "$HOME/.meep/server" serve
# In the second terminal
curl -H "Authorization: Bearer $(cat "$HOME/.meep/server/device-token")" http://127.0.0.1:47950/v1/health
```

Use `--listen`, `--log-level` and `--data-dir` to override the defaults. On macOS the data directory defaults to `~/Library/Application Support/Meep/server`. The first run writes a mode-0600 `device-token`. Use `device add` to pair another device with the implicit owner. To provision a separate user, run `owner add --label "Name"` (the label is optional), then `device add --owner UUID`. `owner list` shows IDs and display labels. `device list` shows token fingerprints and `device revoke FINGERPRINT` disables one credential. The original `token create/list/revoke` commands still work. The authenticated `GET /v1/health` returns `owner_id` for replica selection.

Each owner has private topics, files, views and connections. Use `/owners/UUID/v1/ingest/CONNECTION` for that owner's webhook URL. The original `/v1/ingest/CONNECTION` URL belongs to the implicit owner. Terminate with Ctrl-C or SIGTERM.

New workflow callbacks and agent tools use the HTTPS address in `settings.json` in the server data directory, for example `{"public_base_url":"https://meep.example.org"}`. The saved setting takes precedence over `MEEP_PUBLIC_BASE_URL`. A paired device can send the same JSON to `PUT /v1/settings/public-base-url` to update its owner’s address immediately.

## Connections

Register accounts with `PUT /v1/connections/{id}` and grant the topics that may use them. Pass connector configuration as a JSON string in `secrets.config`. [Connector configuration](../meep-connectors/configuration.md)

- Sign out with `DELETE /v1/connections/{id}/credentials`. The server erases the account credentials, stops polling and reports `signed_out` to paired devices.
- For PostHog, send `access_token`, `refresh_token`, `region` (us, eu or a PostHog origin), `project_id` and the original OAuth `client_id` for refresh. Self-hosted projects use `/mcp` on their origin unless the config specifies `mcp_endpoint`.
- The server polls granted insight, flag and event watches every 30 seconds. Set `secrets.poll_interval_seconds` to change the interval. An event watch defaults to one occurrence in the last hour.
- A plain webhook accepts a meep-ingest Event for its own connection ID. Send its `webhook_secret` in the `x-meep-secret` header. Configured webhooks verify and map the provider payload using their configured header.
- Provision a flow with the per-binding secret returned by the trusted engine. Its callback must send a UUID `Idempotency-Key` per logical step and reuse it on retry. The server stores its result with the effect.
- Scout, Daily brief, Weekly goals and custom `report_to_topic` steps with `op: agent` run a read-only PostHog workflow agent. The following webhook delivers its structured findings to the bound topic. An empty array records a completed run with zero reports. Report threads, the routine run record and the callback receipt commit together.
- To deliver replies to a source, configure its `secrets.reply_workflow` with the PostHog flow UUID. A non-PostHog source also needs `secrets.reply_account`, the ID of a PostHog account granted to the topic. The flow receives `source`, `channel`, `external_id` and `text`. The activity log records the dispatch receipt or failure.
- A proposing flow receives `approved_task`, `action` and the reviewed `draft` when an action is approved. Branch on those variables to execute the approved operation. The engine records its final invocation status on the task.

## Storage and sync

SSE topic event IDs are exclusive sync cursors. Request an older file version with `?revision=N`. File uploads accept a UUID `Idempotency-Key` scoped to the topic and path. Command batches and mapped webhook deliveries accept up to 64 items. File, source, connection and attention lists accept `limit` and `offset`, returning the next offset in `x-meep-next-offset` when another page is available. Request `/v1/sources?complete=true` to receive all sources from one ranking pass.

Archived topics leave default searches and attention lists. Meep suspends intake, dispatch and agent starts. It also pauses active topic-owned schedules and analytics triggers in PostHog and resumes those flows on restore. Independently managed or shared workflows retain their provider configuration.

Deleting a file preserves its earlier revisions. Deleting a topic sends its replicas a tombstone. After every registered replica confirms it has applied the deletion, the server discards retained topic data and file history. A device that stays offline delays this collection.

The host stores topics in SQLite, file revisions in a directory and connector checkpoints in SQLite. Connection credentials use the macOS Keychain or private files elsewhere. Hosted deployments can use `Server::with_storage` to supply their own engine Store, Blobs, connector StateStore, SecretStore, ConnectorFactory and Auth.

## PostHog AI

Each topic has one agent conversation, a PostHog Task resumed turn by turn; setup is its first turn and side work goes through `plan_task`. Writing runs as PostHog Tasks using the registered account. Topics do not automatically provision a Sort inbox workflow. Context references are passive; an explicitly configured source routine may watch matching sources. A running agent task can publish a sourced report to its own topic or another topic shared with its account. Questions stay in task conversations; fact and file conflicts are reviewed by the person.
