# The stateless protocol and how sessions survive it

The MCP `2026-07-28` revision makes the protocol **stateless**. That removes the two things
analytics used to key attribution on — the `initialize` handshake and the `Mcp-Session-Id`
header — so "what is one session?" had to be rebuilt at the application layer. This file is the
reference for that: what the spec says, what the SDK does about it, and what it means for a query.

Verified 2026-08-06 against spec `2026-07-28`, `@posthog/mcp` 0.10.8, `posthog` 7.38.0, and
dotcom master. Versions move fast — re-check before trusting a number here.

## What the spec actually changed

Read the spec itself rather than a summary when it matters:
`docs/specification/2026-07-28/` in `modelcontextprotocol/modelcontextprotocol`. `draft` is
currently byte-identical in substance (its changelog reads "Changes since the most recent release
will accumulate here"), so `2026-07-28` is the live revision.

Two SEPs did the work: **SEP-2575** (Make MCP Stateless) and **SEP-2567** (Sessionless MCP via
Explicit State Handles).

- **`initialize` is removed, not deprecated.** It appears nowhere in the revision, and isn't in
  the deprecated registry either. `basic/versioning.mdx` defines "legacy" as protocols that
  "establish a session with an `initialize` handshake (`2025-11-25` and earlier)". Its
  replacement is `server/discover`, an **optional** probe: servers must implement it, clients
  need not call it.
- **`Mcp-Session-Id` is removed**, and a server must actively ignore one if a legacy client sends
  it: "ignore it, and do not mint or echo session IDs" (`basic/transports/streamable-http.mdx`).
  `Last-Event-ID` and stream resumability go too; GET/DELETE to the endpoint now return 405.
- **No negotiation at all.** "There is no negotiation handshake. Every request carries its
  protocol version, and the server accepts or rejects each request independently."
- **Connections are explicitly not sessions.** "an open connection, such as a STDIO process, is
  not a conversation or session: clients may interleave unrelated requests on the same transport,
  and a server must not treat connection or process identity as a proxy for conversation or
  session continuity."
- **Continuity is the application's job.** "State that needs to span multiple requests ... MUST be
  referenced by an explicit identifier the client passes on each request." That is SEP-2567's
  explicit-state-handle model, and it is the whole basis for what PostHog does below.

Per-request `_meta` keys replace the handshake for identity:

| Key                                          | Required?             | Carries                                                                         |
| -------------------------------------------- | --------------------- | ------------------------------------------------------------------------------- |
| `io.modelcontextprotocol/protocolVersion`    | required              | the version for _this_ request (also the `MCP-Protocol-Version` header on HTTP) |
| `io.modelcontextprotocol/clientCapabilities` | required              | capabilities in use for this request                                            |
| `io.modelcontextprotocol/clientInfo`         | optional, SHOULD send | client name + version                                                           |
| `io.modelcontextprotocol/serverInfo`         | server -> client      | server name + version                                                           |

Two constraints worth internalising:

- **`clientInfo` and `serverInfo` are self-reported and unverified.** The spec says
  implementations "SHOULD NOT rely on them for security decisions" — the rule covers both. Harness attribution built on it is an assertion, not a fact.
- **Read it fresh per request.** There is no handshake to cache it from, and nothing guarantees a
  client sends identical `clientInfo` across a run.

**There is no `conversation_id` in the spec.** Grepping the revision for `conversationId` /
`conversation_id` / `agentId` returns nothing. PostHog's conversation handle is our own
application-level state handle, implementing SEP-2567's pattern — don't go looking for it in the
spec, and don't assume another vendor's server has one.

If you add custom `_meta` keys: any prefix whose **second** dot-label is `modelcontextprotocol` or
`mcp` is reserved. `com.posthog/` is fine; `io.mcp.posthog/` is not.

Smaller changes that occasionally bite: `structuredContent` may now be any JSON value rather than
an object, `ping` and `logging/setLevel` are gone, and tasks moved to the
`io.modelcontextprotocol/tasks` extension (so `io.modelcontextprotocol/related-task` no longer
exists).

## How `$session_id` is resolved now

`packages/mcp/src/extensions/session.ts::getSessionId` resolves **first match wins**:

1. **The agent's `conversation_id` tool argument** — if present and shape-valid.
   `$session_id = deriveSessionIdFromConversation(handle)`, a deterministic unsalted hash into the
   `ses_` namespace. Deterministic is the point: two pods that never shared state derive the same
   id from the same handle. This branch deliberately does **not** write the shared
   `sessionId`/`lastActivity`, because that would leak one chat's session onto a concurrent
   chat's `tools/list`. It does still call `applyTokenClientIdentity`, writing client
   name/version/protocol version into `sessionInfo` — per-connection identity, not per-chat
   session.
2. **A request-carried session id** — the SDK's own token on `Mcp-Session-Id` (`decodeSessionId`),
   else the transport's raw `extra.sessionId` hashed. This is the legacy `2025-11-25` path.
3. **In-memory** — the id this server instance already holds, rolling over after
   `INACTIVITY_TIMEOUT_IN_MINUTES` (30) of inactivity. Covers stdio and anything carrying
   neither of the above.

Subtle, and worth knowing before you debug a session that changed mid-conversation: the handle
branch does not advance `lastActivity`, and — narrowing it — `getSessionIdFromMemory` only
rotates when `sessionSource === 'generated'`; once a token or transport id has been read the
source is `'token'`/`'mcp'` and no rotation happens. Where it does apply, so a conversation that always echoes lets the
in-memory fallback age past that timeout. A later call that arrives _without_ a handle therefore
rotates to a fresh session. That is intended — by then the fallback session really has been idle
that long — but it means "the agent stopped echoing" and "the session rotated" look the same in
the data.

So the conversation handle is a _new step 1_ in front of the mechanism the older docs describe —
the legacy paths still work and still matter for legacy clients.

> **`enableConversationId` is off by default.** When off it is "fully inert: no parameter is
> injected, no schema is touched, no prompt-back is appended, and `$session_id` resolves exactly
> as it did before". So a stateless client against a server with the flag off has no transport
> session _and_ no handle, and lands on step 3 — sessions fragment, often to one per request.
> **That is the first thing to check when someone reports fragmented or single-call sessions.**

`$session_id` and `$mcp_conversation_id` are different values on the same event: `$session_id` is
`ses_<hash-of-handle>`, `$mcp_conversation_id` is the raw handle.

## The session handle: mint, deliver, echo, verify

The handle is the `conversation_id` seen from the wire side — how the agent learns the value it
must send back.

**Mint.** `conversation-id.ts::resolveConversationId` decides per call: disabled -> none; the agent
echoed a handle the SDK could have minted -> use it; anything else (absent, or invented) -> mint a
fresh uuidv7 and prompt it back.

**Verify — and why the shape gate exists.** Only a value matching the uuidv7 shape the SDK mints
is accepted. From the source, and worth quoting in full because the reasoning is the rule:

> The shape check matters because this value becomes `$session_id`, and the derivation is
> deterministic so that two pods agree — which also means two _callers_ sending the same string
> land in the same session. The strings agents invent are not random (`conv-1`, `1`, `session`),
> so trusting them verbatim would silently merge unrelated conversations, potentially across
> users.

A compliant agent echoing the minted uuidv7 is unaffected. The gate narrows the risk rather than
eliminating it — two callers independently choosing the same well-formed uuidv7 would still merge.
That residual is accepted because `$session_id` is an analytics grouping key, not a security
boundary. Don't treat it as one.

**Deliver.** Two channels, because one was not enough:

| Channel                               | When                                                                                   | Where                                     |
| ------------------------------------- | -------------------------------------------------------------------------------------- | ----------------------------------------- |
| Text block in `content`               | only on the call that **minted** it, plus errored results (#4433)                      | `injectConversationIdPromptBack`          |
| `structuredContent._mcp_instructions` | every response **from an instance that served the `tools/list`** for that tool (#4431) | `mirrorInstructionsIntoStructuredContent` |

The second exists because clients that read structured results never see the `content` text block
— correlation for those tools measured 0/15 against Claude Code before the fix, 15/15 after
(figures from the #4430/#4431 PR bodies; they aren't reproducible from source).

**The mirror's real gate is not "the schema declares the key" — it is "this instance served the
listing".** `instrumentation.ts::getActiveAnalyticsParameterOwnership` requires
`listed?.outputInstructions === true`, and `listed` comes from a per-instance `Map` written only
by the `tools/list` handler. The source is blunt about the consequence: "an instance that never
serves a listing never writes the mirror at all. That is the per-request server pattern —
`tools/list` lands on one instance, `tools/call` on a cold one — where the handle falls back to
the `content` block and a structuredContent-only client misses it." Failing closed is deliberate
(writing an undeclared key fails the whole result), and the noted fix — a process-scoped cache —
has not landed. So under exactly the per-request-instance deployments this revision encourages,
the recovery channel is the one most likely to be absent.

Worse on the **low-level `Server` path**: `instrument-lowlevel.ts::handleToolCallRequest` passes
no ownership override, so `conversationId` collapses to `listed?.conversationId` too. A cold
per-request low-level instance resolves no handle at all — step 1 of the resolution order never
fires. The high-level path is saved by an explicit override; the low-level path is not.

Shape under the `_mcp_instructions` key: `{ conversation_id: string, instructions: string }`, where
`instructions` is the fixed line telling the agent to send the id on every subsequent call.

If neither channel can carry it (no declared output schema, and a result with no `content` array),
the SDK clears `event.conversationId` rather than reporting a conversation the agent was never
told about.

**`_mcp_instructions` is a hard prerequisite, not decoration.** MCP clients ajv-validate
`structuredContent` against the schema from `tools/list` under `additionalProperties: false`. An
undeclared key doesn't get dropped — it fails the _entire_ tool result. So #4430 shipped the schema
declaration alone (inert), and only then could #4431 write into it. If you add anything to
`structuredContent`, declare it first or you break the tool.

Also as of #4433 the handle reaches the virtual `get_more_tools` tool, so a reported capability gap
groups with the work that hit it instead of falling back to the transport session.

## Where each repo stands

> **None of the session model above applies to PostHog's own dogfood data yet.** `services/mcp`
> uses the custom-dispatcher (`PostHogMCP`) path, pins `@posthog/mcp@0.10.2`, and sources
> `$mcp_conversation_id` from an **`mcp-conversation-id` HTTP header** rather than a tool
> argument (`src/index.ts`) — its `$session_id` is not derived from it. The code comment says the
> tool-arg path arrives "once the SDK is bumped with `enableConversationId`". So when you query
> project 2, you are looking at header-supplied conversation ids and transport-derived sessions,
> not the mint/echo loop.

**`services/mcp` — dual-dialect at the protocol layer, already shipped.** `src/lib/stateless-protocol.ts` (#72223)
defines `STATELESS_PROTOCOL_VERSION = '2026-07-28'`, the reserved `_meta` keys, `server/discover`,
the SEP-2243 operation headers (`MCP-Protocol-Version`, `Mcp-Method`, `Mcp-Name`), and error codes
`-32022` (unsupported protocol version) and `-32020` (header mismatch). `dispatcher.ts` picks the
dialect per request from `_meta`'s protocol-version key or the header, then branches: legacy
clients still get `initialize`/`ping`, modern clients get `server/discover` and **no session
minting**. So the server speaks both today.

**TypeScript SDK — shipped through 0.10.8.** The session model above is current.

**Python SDK (`posthog` 7.38.0) — this is the part still in flight.** Conversation-id already
exists (`posthog/mcp/_conversation_id.py`), and 7.30.0/7.33.0 brought multi-pod session tokens and
`$mcp_protocol_version`. But those are the _legacy_ handshake mechanism scaled across pods, not
spec-stateless support. Open and unmerged:

- **posthog-python#803** — read client identity from request `_meta`, closing the parity gap with
  TS 0.10.1.
- **posthog-python#830** — MCP 2026-07-28 + mcp 2.x SDK support: an adapter via the official
  `ServerMiddleware`, plus `_derived_sessions.py` deriving `$session_id` from
  `(distinct_id, client_name, client_version)` per SEP-2567 guidance now the header is gone. Adds
  `$mcp_result_type` and `$mcp_session_id_source`.

Treat Python as _not yet_ spec-stateless until those land, and don't promise TS/Python parity on
`_meta` identity.

## Telling which model produced a session, from the data

The mechanism above is invisible in the events unless you know what to look at, and two things
that look diagnostic are not:

- **The `ses_` prefix does not discriminate.** All three branches mint `ses_`-prefixed ids
  (`newPrefixedId('ses')` and `deterministicPrefixedId('ses', ...)` in `session.ts`), so the
  prefix tells you nothing about which one ran.
- **You cannot recompute the hash.** `deriveSessionIdFromConversation` is not exported from the
  package entry point, so you cannot verify from outside that a given `$session_id` derives from
  a given handle.

What you _can_ read off the events:

| Signal                                              | Reading                                                                                                                 |
| --------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `$mcp_protocol_version` = `2026-07-28`              | the request came in on the stateless dialect                                                                            |
| `$mcp_conversation_id` populated                    | `enableConversationId` is on **and** the handle reached the agent and came back — this session is conversation-anchored |
| `$mcp_conversation_id` empty on a stateless request | either the flag is off, or the handle never completed the round trip                                                    |
| one `$session_id` per `$mcp_tool_call`, repeatedly  | fragmentation — the symptom that sends people here                                                                      |

So the useful first query on a suspect project is a count of distinct `$session_id` against
distinct `$mcp_conversation_id` and calls, sliced by `$mcp_protocol_version`. Sessions roughly
equal to calls, with `$mcp_conversation_id` empty, is the fragmentation signature.

**If the flag is on and sessions still fragment**, the handle is not completing the round trip.
In order of likelihood: the tool has no declared output schema, so the `structuredContent` mirror
can't carry the handle and a structured-output client never sees the `content` text block; the
agent is echoing a value that isn't the minted uuidv7, which the SDK treats as absent rather than
as a session key; or the minting call returned a result with no `content` array and no declared
schema, in which case the SDK deliberately drops the handle rather than report a conversation the
agent was never told about.

## Consequences for queries and debugging

- **Fragmented or one-call sessions** on a stateless client almost always means
  `enableConversationId` is off (or the agent isn't echoing the handle). Check the flag before
  suspecting ingestion.
- **`$mcp_initialize` is not a session-start anchor, and whether it fires at all depends on whose
  server you're looking at.** A customer server on the SDK's `instrument()` path emits nothing for
  a stateless client — that path patches the `initialize` handler and knows nothing of
  `server/discover`. PostHog's own `services/mcp` does emit it, from both entry points
  (`dispatcher.ts::recordDiscoveryRequest`). Live consequence, customer servers only: the
  onboarding query in `frontend/mcpAnalyticsOnboardingLogic.ts` computes
  `countIf(event = '$mcp_initialize') > 0 AS has_initialize`, and `manifest.tsx` lists
  `waitingEvents: ['$mcp_initialize']`. Onboarding still _completes_ — `hasToolCall` is checked
  first in both that selector and `statusFromProbeDefinitions` — but the intermediate "connected,
  no calls yet" state is unreachable, so such a project reads as `not-instrumented` until its
  first tool call. No fix is in flight; don't diagnose it as ingestion.
- **`$session_id` grouping is only as good as handle delivery.** A tool with no declared output
  schema, called by a structured-output client, may never receive the handle.
- **Protocol version is per-request now.** `$mcp_protocol_version` can legitimately differ between
  events that a legacy mental model would call "one session" — break metrics down by it rather
  than assuming one value per session.
- **Error codes were renumbered at the revision boundary** (`-32001` -> `-32020`, `-32003` ->
  `-32021`, `-32004` -> `-32022`, resource-not-found `-32002` -> `-32602`). Anything bucketing on
  the raw code silently miscategorises across that boundary.
- **Harness/client attribution is self-reported** under the stateless model, per the spec's own
  warning. Fine for product analytics, not for anything trust-bearing.
