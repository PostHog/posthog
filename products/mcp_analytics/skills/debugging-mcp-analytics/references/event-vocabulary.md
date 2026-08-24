# MCP analytics event vocabulary

Source of truth for SDK-emitted names: `packages/mcp/src/extensions/constants.ts` in
`PostHog/posthog-js`, exported as `PostHogMCPAnalyticsEvent` / `PostHogMCPAnalyticsProperty`.
PostHog-side descriptions, including everything the SDK does not define, live in
`posthog/taxonomy/taxonomy.py`. **When this file and those disagree, they win** — grep them.

Properties fall into three groups, and the distinction matters: SDK-emitted properties exist
for any instrumented customer server, server-stamped ones exist only for PostHog's own
dogfood traffic, and exec-mode ones only appear when a server runs a single `exec` dispatcher.

## Events

All `$`-prefixed — a non-`$` name would be treated as a customer event.

| Event                                        | Notes                                                                                                                                                                                                                 |
| -------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `$mcp_tool_call`                             | The primary event. Almost every metric aggregates over it.                                                                                                                                                            |
| `$mcp_tools_list`                            | A `tools/list` request. Carries the advertised catalog — the basis for zombie-tool queries.                                                                                                                           |
| `$mcp_initialize`                            | The `initialize` handshake. **Not emitted by clients on the MCP 2026-07-28 stateless revision**, which removes the handshake — do not use it as a universal session anchor.                                           |
| `$mcp_missing_capability`                    | The agent wanted something the server does not offer. The clearest roadmap signal in the dataset.                                                                                                                     |
| `$mcp_auth_failed`                           | A request refused before a session existed — a rejected credential, or a scope the API denied. **PostHog's own server only, not the SDK.** The one MCP event with no organization/project, because none was resolved. |
| `$mcp_resource_read` / `$mcp_resources_list` | Resource access. Not emitted by `instrument()` in either SDK.                                                                                                                                                         |
| `$mcp_prompt_get` / `$mcp_prompts_list`      | Prompt access. Same caveat as resources.                                                                                                                                                                              |
| `$identify`                                  | Person identity. Since TS 0.9.1 this fires at most once per session, not before every tool call.                                                                                                                      |
| `$exception`                                 | Error sibling event. Can be disabled, and is not emitted when no error value is passed — see the failures rule below.                                                                                                 |

`$mcp_custom` is registered in the enum, but `analytics.capture()` sends the verbatim event
name it is given rather than `$mcp_custom`.

## SDK-emitted properties

On `$mcp_tool_call` unless noted. These are the properties any instrumented server produces.

| Property                                   | Notes                                                                                                                                                                                                                                                                                                                                                                                              |
| ------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `$mcp_tool_name`                           | The tool the agent called. In single-exec mode this holds the resolved inner tool, or the literal `exec` when unrecognized — see exec-mode below.                                                                                                                                                                                                                                                  |
| `$mcp_tool_description`                    | The description the agent saw. In single-exec mode this is the dispatcher's static text on every call.                                                                                                                                                                                                                                                                                             |
| `$mcp_tool_category`                       | Server-assigned grouping. Used by the Signals scout to group problem tools.                                                                                                                                                                                                                                                                                                                        |
| `$mcp_intent`                              | Why the agent made the call — the product's differentiator. Populated from the injected `context` argument, or a configured fallback.                                                                                                                                                                                                                                                              |
| `$mcp_intent_source`                       | `context_parameter` or `inferred`. Tells you whether the agent actually filled the context argument.                                                                                                                                                                                                                                                                                               |
| `$mcp_is_error`                            | Boolean failure flag. **The canonical failure signal.**                                                                                                                                                                                                                                                                                                                                            |
| `$mcp_duration_ms`                         | Call latency. Cast before aggregating: `quantile(0.95)(toFloat(properties.$mcp_duration_ms))`.                                                                                                                                                                                                                                                                                                     |
| `$mcp_parameters`                          | Captured arguments, sanitized.                                                                                                                                                                                                                                                                                                                                                                     |
| `$mcp_response`                            | Captured response, sanitized. May be empty by configuration.                                                                                                                                                                                                                                                                                                                                       |
| `$mcp_listed_tool_names`                   | On `$mcp_tools_list`. JSON array of advertised tools. Diff against called tool names for zombie tools. In single-exec mode `$mcp_exec_inner_tool_names` is the intended catalog field, but is unemitted today — see exec-mode below.                                                                                                                                                               |
| `$mcp_error_type`                          | Since TS 0.8.0. Low-cardinality label — `validation`, `permission`, `timeout`, `rate_limited`, etc. Defaults to the thrown error's type; hosts can pass an explicit label.                                                                                                                                                                                                                         |
| `$mcp_error_message`                       | Since TS 0.8.0. Redacted automatically as of TS 0.10.2.                                                                                                                                                                                                                                                                                                                                            |
| `$mcp_client_name` / `$mcp_client_version` | The calling client as _it_ reported itself. One mid-priority input to harness resolution — not the harness label.                                                                                                                                                                                                                                                                                  |
| `$mcp_server_name` / `$mcp_server_version` | The instrumented server's own identity.                                                                                                                                                                                                                                                                                                                                                            |
| `$mcp_protocol_version`                    | Since TS 0.10.0. The negotiated MCP spec version. On legacy `initialize`-handshake sessions it is stamped on `$mcp_initialize` and every subsequent event of that session; under the 2026-07-28 revision it is **per request**, so one `$session_id` can legitimately span more than one value — don't treat it as a session constant. See [stateless-and-sessions.md](stateless-and-sessions.md). |
| `$mcp_conversation_id`                     | The conversation handle: **server-minted on the first call, agent-echoed thereafter** (an invented value is rejected and replaced). **Survives reconnects, but only when the server sets `enableConversationId`** (off by default) — see identifiers below and [stateless-and-sessions.md](stateless-and-sessions.md).                                                                             |
| `$mcp_resource_name`                       | On resource events.                                                                                                                                                                                                                                                                                                                                                                                |
| `$session_id`                              | The standard PostHog session id, materialized. The usual grouping key.                                                                                                                                                                                                                                                                                                                             |
| `$mcp_source`                              | Always `posthog_mcp_analytics`. The reliable way to isolate MCP events from everything else on the `events` table.                                                                                                                                                                                                                                                                                 |

## Server-stamped properties

Added by PostHog's own server (`services/mcp/src/hono/analytics.ts::buildBaseProperties`),
**not** by the SDK. They exist for PostHog's dogfood data and will be absent for a customer
server, so never rely on them in customer-facing queries or docs without checking.

`$mcp_session_id` (transport-level), `$mcp_region`, `$mcp_mode`, `$mcp_consumer`,
`$mcp_version`, `$mcp_client_user_agent`, `$mcp_transport`, `$mcp_auth_method`,
`$mcp_organization_id`, `$mcp_project_id`, `$mcp_project_uuid`, `$mcp_project_name`,
`$ai_product` (`mcp`), and the non-`$`-prefixed `mcp_runtime` (`hono`) and
`mcp_vendor_client` — the last of which is the **top-priority harness signal**, so it
appears inside harness SQL.

`$mcp_auth_method` (`oauth`, `personal_api_key`, `id_jag`, `none`, `unknown`) comes from the
bearer token's prefix. It is the only way to tell an OAuth connector apart from an API-key
connection, which matters when reading a recovery: a user who works around a broken OAuth
flow by pasting a personal API key produces traffic that otherwise looks identical to the
connector having been fixed.

On `$mcp_auth_failed`: `$mcp_auth_failure_reason` (`insufficient_scope`,
`inactive_oauth_token`, `invalid_api_key`, `unknown`), `$mcp_missing_scope` when the API named
one, and `$mcp_auth_status` (401 or 403). It deliberately does **not** set `$mcp_is_error` or
`$mcp_error_status` — those mean "a tool call failed", and reusing them would fold auth
refusals into tool error rates, which is also why the status has its own field. Its
`distinct_id` is the token hash, not a user id, so it joins to other MCP events by client and
time, never by person.

Per-event additions: `$mcp_error_status` (upstream HTTP status), `$mcp_error_code` (machine-readable leaf failure code: the API's validation error code or the exec rejection reason), and `$mcp_error_field` (the validation error's field path, array indexes normalized to `N`, e.g. `actions__N__inputs__email`) — all stamped by `services/mcp/src/hono/tool-executor.ts` — **server-side, despite sitting next to the SDK's typed error properties in queries**; and `tool_count`, `read_only`, `via_sse_redirect` on `$mcp_initialize`. Failed calls may also carry
`$mcp_validation_fields` and `$mcp_validation_input_keys` (which fields failed validation, and
which keys the caller actually sent), and exec-mode calls carry `$mcp_exec_verb` (which dispatcher
verb ran) and `$mcp_exec_target_tool` (the tool that `info`/`schema`/`call` named). Those four are
stamped in `tool-executor.ts` but are **not registered in `posthog/taxonomy/taxonomy.py`**, so they
have no descriptions in the property picker — they still query fine. `execute-sql` calls additionally emit a separate `$ai_generation` event
carrying `$ai_trace_id`, `$ai_input`, `$ai_output_choices`, and `$ai_latency`.

## Exec-mode properties

When a server exposes a single `exec` dispatcher instead of many tools, the inner tool has to be
recovered from the exec command's `call <tool> ...` form.

**Read this before writing an exec-mode query.** These properties are registered in
`posthog/taxonomy/taxonomy.py` and coalesced by the read path, but **no producer on master emits
them**. `services/mcp`'s `ToolExecutor.callExecTool()` resolves the inner tool itself and passes
it to `trackToolCall()` as the tool name, falling back to the literal `exec` when the command
isn't recognized — so in current data the inner tool arrives in `$mcp_tool_name`, and these
dedicated fields are empty. A query built only on them returns nothing.

| Property                          | Notes                                                                                                                                                   |
| --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `$mcp_exec_tool_call_name`        | The inner tool invoked. Read it via `EFFECTIVE_TOOL_SQL` (`backend/hogql_queries/base.py`), which coalesces it ahead of `$mcp_tool_name` — never alone. |
| `$mcp_exec_tool_call_description` | The inner tool's description rather than the dispatcher's static text.                                                                                  |
| `$mcp_exec_inner_tool_names`      | On `$mcp_tools_list`: the inner catalog, intended to stand in for `$mcp_listed_tool_names` in this mode.                                                |

So for per-tool aggregation, always go through `EFFECTIVE_TOOL_SQL` — it is correct whether the
inner tool arrives in `$mcp_tool_name` (current) or in the dedicated property (historical rows,
and whatever lands when the emitter ships). For zombie tools, prefer `$mcp_listed_tool_names`
and treat `$mcp_exec_inner_tool_names` as a fallback that is empty today; if a zombie-tool query
returns no tools at all, that absence is the first thing to check.

## The three identifiers

> Under the stateless spec `$session_id` may be derived from the conversation handle rather than
> the transport — see [stateless-and-sessions.md](stateless-and-sessions.md) for the resolution
> order before relying on the model below.

A frequent source of wrong session math:

- **`$session_id`** — the standard PostHog session id, a materialized column. The default
  grouping key for "a session" in this product.
- **`$mcp_session_id`** — transport-level, from the `Mcp-Session-Id` header. **Rotates on
  reconnect**, so counting it overcounts sessions.
- **`$mcp_conversation_id`** — server-minted on the first call, agent-echoed after (an invented
  value is rejected and replaced). **Survives reconnects**, so it is the right key
  for "one agent conversation" spanning drops.

## Library identity

Since TS 0.7.0 events stamp the standard `$lib` = `posthog-node-mcp` (plus `$lib_version`) via
`applyMcpLibIdentity`. The short-lived 0.6.0 custom `$mcp_lib` / `$mcp_lib_version` properties
were dropped — any document mentioning them is stale.

Note that posthog-node sets `$lib` at the client level, so `instrument()` relabels **every**
event sent by the client you pass it. Give an MCP server a posthog-node client dedicated to its
analytics rather than sharing the app's.

## TypeScript SDK behaviour by version

Read `packages/mcp/CHANGELOG.md` for the current list; this covers the changes that alter data
semantics rather than the API surface.

- **0.5.0** — `instrumentMutator(posthog)`, a point-free `(server) => server` helper for
  framework server-mutation hooks such as `@rekog/mcp-nest`'s `serverMutator`.
- **0.7.0** — standard `$lib` identity (above).
- **0.8.0** — typed `$mcp_error_type` / `$mcp_error_message` on failed calls, so failures can
  be broken down by reason without joining to `$exception`.
- **0.9.0** — **stateless sessions.** Mints an `Mcp-Session-Id` response header at
  `initialize` encoding the session id plus client name/version, so multi-pod and stateless
  servers stop fragmenting sessions. Auto-minting requires `enableJsonResponse: true` on
  `StreamableHTTPServerTransport`; SSE-mode servers set the header at the HTTP layer using the
  exported `encodeSessionId`, `decodeSessionId`, `MCP_SESSION_HEADER`, and `newSessionId`.
  This is now the _legacy handshake_ identity path.
- **0.9.1** — standalone `$identify` fires at most once per session (at `initialize`, on
  first-seen identity, or on a material identity change) rather than before every tool call.
  `distinct_id` and `$set` still ride every event, so no person data is lost.
- **0.10.0** — `$mcp_protocol_version` (above), persisted in session info and recovered
  cross-pod from the session token.
- **0.10.1** — the MCP 2026-07-28 stateless revision removes the `initialize` handshake and
  the `Mcp-Session-Id` header for clients on it. The SDK therefore also reads client
  name/version and protocol version from **every request's** `params._meta`
  (`io.modelcontextprotocol/clientInfo`, `io.modelcontextprotocol/protocolVersion`) and stamps
  them per request rather than into shared session state — so concurrent multiplexed requests
  from different clients cannot clobber each other's attribution. Clients without `_meta` fall
  back to the session-token path unchanged.
- **0.10.2** — exception messages and large binary payload encodings are redacted
  automatically, through the same sanitizer as parameters and responses. Unconditional, with
  no configuration knob.
- **0.10.3-0.10.7** — argument-preservation, per-server logger isolation, missing-capability
  name collisions, and a fix for concurrent requests leaking identity/session attribution.
- **0.10.8** — the largest data-semantics change in this list: `$session_id` can now be anchored
  to an agent-echoed `conversation_id`, and tool results may carry an `_mcp_instructions` key.
  See [stateless-and-sessions.md](stateless-and-sessions.md); do not reason about sessions from
  this list alone.

## Python SDK parity

`posthog/mcp/` in `PostHog/posthog-python`, mirroring the `posthog.ai` layout. `instrument()`
covers the official SDK's FastMCP and low-level `Server`, **and** jlowin's standalone
fastmcp 2.0 (routed via its `_mcp_server`, stripping the injected `context` because that
library rejects unexpected kwargs). `PostHogMCP` covers custom dispatchers.

Has: stateless sessions, `$mcp_protocol_version`, once-per-session `$identify`, payload
sanitization. Resources and prompts are intentionally omitted, matching TS `instrument()`.

**Known gaps against the TypeScript SDK** — verify before promising parity:

- no typed `$mcp_error_type` / `$mcp_error_message` taxonomy (the largest gap)
- no `_meta`-based client identity for the 2026-07-28 stateless revision
- no `instrumentMutator` equivalent

## Query gotchas

- Aggregate per tool on the **effective** tool name, coalescing `$mcp_exec_tool_call_name`
  ahead of `$mcp_tool_name`.
- Take failures from `$mcp_is_error` (with `$mcp_error_type` / `$mcp_error_status` for the
  reason), never from `$exception`, which can be absent by design and so returns nothing
  rather than erroring.
- Group clients by the resolved **harness** label, not raw `$mcp_client_name`.
- Zombie tools = `arrayJoin($mcp_listed_tool_names)` from `$mcp_tools_list`, minus the distinct
  effective tool names seen on `$mcp_tool_call`. `$mcp_exec_inner_tool_names` is the intended
  single-exec equivalent but is unemitted today, so a query resting on it returns nothing.
- Scope to `$mcp_source = 'posthog_mcp_analytics'` to isolate MCP events.
