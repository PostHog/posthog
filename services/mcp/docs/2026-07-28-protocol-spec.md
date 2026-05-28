<!-- markdownlint-disable MD013 -->

# MCP `2026-07-28` parallel pipeline — implementation spec

**Status:** draft, no code yet.
**Branch:** `yasen/mcp-2026-07-28-spec` (off `yasen/mcp-confirmation-paradigm`).
**Owners:** TBD.
**Target protocol version:** `MCP-Protocol-Version: 2026-07-28` (RC locked 2026-05-21, final 2026-07-28).

This document specifies the changes needed for the Hono MCP server to support
the `2026-07-28` protocol alongside the current `2025-06-18` protocol. The two
implementations live side-by-side — every inbound HTTP request is dispatched to
the right pipeline based on the protocol version the client declares. We do
not break, deprecate, or remove the existing pipeline; clients on older
protocols continue to receive the same responses they get today.

The motivating consumer is the `confirmation:` YAML paradigm shipped in PR
60195: today its elicitation flow rides our cross-pod session bus over SSE,
which the new protocol explicitly removes. After this work, a confirmation
gate gracefully degrades to the new continuation-passing form when the client
is on `2026-07-28`, and continues to use the bus when the client is on
`2025-06-18`. Tool authors do not see the difference.

## 1. Why a parallel pipeline

The `2026-07-28` RC is a deliberate breaking change to the on-the-wire model
for server-initiated requests. The headline:

> "Server-initiated requests may now only be issued while the server is
> actively processing a client request." — SEP-2260
>
> "These [server-initiated] interactions are embedded as input requests inside
> an `IncompleteResult` returned from specific request paths (e.g.,
> `CallTool`, `GetPrompt`, `ListResources`). The client satisfies the input
> requests and retries the original request." — SEP-2575, §Response Streaming

The SSE-elicit-then-await pattern that drives our `ElicitBinding` +
`SessionResponseBus` infrastructure cannot be expressed on `2026-07-28` — there
is no SSE write-back channel for an `elicitation/create` request, and the
server cannot block waiting for a reply on the same HTTP request. The
equivalent flow is:

1. Tool handler decides it needs input → returns synchronously with
   `resultType: "input_required"` plus an `inputRequests` map and an opaque
   `requestState` blob.
2. HTTP request ends. Server keeps no state.
3. Client renders prompts, collects responses, **issues a new `tools/call`**
   with the original arguments _and_ `inputResponses` + the echoed
   `requestState`.
4. Any server instance picks up the retry. Tool handler resumes from
   `requestState`, completes the action.

The new model also removes the `initialize`/`initialized` handshake, the
`Mcp-Session-Id` header, and adds two new mandatory HTTP headers
(`Mcp-Method`, `Mcp-Name`) — see §2 for the full surface.

Today every Claude Code surface that exists (interactive CLI, Desktop, the VS
Code extension, Cursor's MCP client) ships `2025-06-18`. The RC has a
10-week SDK validation window before the final spec date, and even after
final, third-party clients will lag the spec by months. We have to keep the
old pipeline running indefinitely. Doing so as a parallel implementation
keeps the new code isolated, reviewable in one PR, and unambiguous about
which protocol version each line belongs to.

## 2. Protocol summary — `2026-07-28` on the wire

This section is a self-contained reference of the wire-level changes we need
to implement. Every quote is from the merged SEP or RC blog post.

### 2.1 Protocol version negotiation (SEP-2575)

- `initialize` / `notifications/initialized` are **removed**. There is no
  handshake.
- Every request carries `MCP-Protocol-Version: <version>` as an HTTP header.
- The same version MUST be present in `_meta["io.modelcontextprotocol/protocolVersion"]`
  on the request body. Header/body mismatch → `400 Bad Request`.
- If the server does not implement the requested version, it returns
  JSON-RPC error code `-32004 UNSUPPORTED_PROTOCOL_VERSION` with body
  `{ supported: string[], requested: string }`. HTTP status `400`.
- New RPC `server/discover` lets the client query supported versions +
  capabilities + serverInfo + instructions up-front. Clients MAY skip it.

### 2.2 Per-request client capabilities (SEP-2575)

- Capabilities live in `_meta["io.modelcontextprotocol/clientCapabilities"]`
  on **every** request — not once per session.
- Client info lives in `_meta["io.modelcontextprotocol/clientInfo"]` on every
  request.
- The `_meta` shape:

  ```ts
  interface RequestMetaObject {
    progressToken?: ProgressToken
    'io.modelcontextprotocol/protocolVersion': string // required
    'io.modelcontextprotocol/clientInfo': Implementation // required
    'io.modelcontextprotocol/clientCapabilities': ClientCapabilities // required
    'io.modelcontextprotocol/logLevel'?: LoggingLevel // optional
  }
  ```

- Missing any required `_meta` field → server returns `INVALID_PARAMS`
  (`400 Bad Request`).
- Missing capability the server needs to serve the request →
  `-32003 MISSING_REQUIRED_CLIENT_CAPABILITY` with
  `data.requiredCapabilities: ClientCapabilities`.

### 2.3 Sessions are gone (SEP-2567)

- `Mcp-Session-Id` header is **removed** from the protocol. Servers MUST NOT
  rely on it; clients MUST NOT send it as a routable identifier.
- All cross-call state moves to "explicit state handles" — a server-minted
  identifier returned from one tool call and threaded as an ordinary string
  argument into subsequent calls. This is a tool-design pattern, not a
  protocol feature; there is no `handles/*` RPC.

### 2.4 Server-initiated requests must be associated with a client request (SEP-2260)

- `elicitation/create`, `sampling/createMessage`, and `roots/list` MUST be
  issued only in the context of an originating `tools/call`, `resources/read`,
  or `prompts/get`.
- They MUST NOT be sent as standalone server-initiated requests on a separate
  channel. The GET-SSE notification channel still exists for `ping`-style
  notifications only.
- The mechanism for delivering them is `InputRequiredResult` (next section).

### 2.5 Multi-Round-Trip Requests (SEP-2322, the load-bearing one)

#### `InputRequiredResult` — replaces the old elicit-over-SSE flow

```ts
type ResultType = 'complete' | 'input_required'

interface Result {
  _meta?: MetaObject
  resultType: ResultType // new — absent ≡ "complete" for back-compat
  [key: string]: unknown
}

interface InputRequiredResult extends Result {
  resultType: 'input_required'
  inputRequests?: InputRequests
  requestState?: string // opaque to client; MUST be echoed verbatim
}

interface InputRequests {
  [key: string]: InputRequest
}

type InputRequest = ElicitRequest | CreateMessageRequest | ListRootsRequest
```

- Keys are author-chosen strings (`"github_login"`, `"confirm"`); they are
  the correlation between an input request and the matching response.
- Sent as a normal JSON response on the original HTTP request — _not_ over
  SSE. The SEP says SSE is allowed but discouraged: "implementations are
  encouraged to prefer the former [single response]".

#### `InputResponses` — what the client sends back

The client re-issues the same RPC method (e.g. `tools/call`) with the original
arguments AND two extra params:

```ts
interface InputResponseRequestParams extends RequestParams {
  inputResponses?: InputResponses
  requestState?: string // verbatim from server's earlier InputRequiredResult
}

type InputResponse = ElicitResult | CreateMessageResult | ListRootsResult
```

- The retry uses a **different JSON-RPC `id`** — "the JsonRPC Id MUST be
  different between the requests sent in step 1 and step 3" (SEP-2322).
- Any server instance can process the retry — that's the whole point.

#### `requestState` semantics

- Opaque to the client.
- The client MUST echo it verbatim — "Clients MUST NOT inspect, parse, modify,
  or make any assumptions about the `requestState` contents."
- Server MUST treat the client as untrusted: validate / authenticate /
  decrypt / re-bind to the authenticated principal.
- Recommended encoding: signed JWT or AES-GCM. Plain JSON is allowed only if
  every field is re-validated as untrusted input.
- Multi-user replay defense: "if the request state contains any data that is
  specific to the original user, the server MUST … cryptographically bind the
  data to the original user and MUST verify that the `requestState` data sent
  by the client is associated with the currently authenticated user."

#### Which RPCs may return `InputRequiredResult`

| ClientRequest    | InputRequiredResult |
| ---------------- | :-----------------: |
| `tools/call`     |         Yes         |
| `resources/read` |         Yes         |
| `prompts/get`    |         Yes         |
| `tasks/payload`  |         Yes         |
| everything else  |         No          |

#### Error handling for malformed `inputResponses`

> "If the missing information requested is necessary for the server to process
> the request, then it SHOULD respond with a new `InputRequiredResult`."

The pattern is: if the retry's `inputResponses` don't satisfy the prompts you
asked for, ask again with a fresh `InputRequiredResult`. Don't return a
protocol error.

### 2.6 HTTP header standardization (SEP-2243)

- Required on every POST:
  - `Content-Type: application/json`
  - `MCP-Protocol-Version: 2026-07-28` (from SEP-2575)
  - `Mcp-Method: <jsonrpc method>` (e.g. `tools/call`)
- Required on `tools/call`, `resources/read`, `prompts/get`:
  - `Mcp-Name: <params.name or params.uri>`
- The server MUST reject mismatches between the header value and the body
  value with `400 Bad Request`. Routing infrastructure may use the headers
  without parsing the body.

### 2.7 SSE narrowed (SEP-2575)

- A response MAY still be delivered as an SSE stream when the response itself
  contains notifications (`notifications/progress`, `notifications/message`).
- Server-initiated `elicitation/create` requests are **not** delivered on
  SSE under any condition — they only appear embedded in an `InputRequiredResult`.
- Resumable streams (`Last-Event-ID` reconnection) are removed. A dropped
  connection means the request is cancelled.

### 2.8 Notification subscriptions (SEP-2575)

- The HTTP `GET /mcp` endpoint is **removed**. All communication is POST.
- A new `subscriptions/listen` RPC opens a long-lived POST whose response is
  an SSE stream of notifications (`tools/list_changed`,
  `prompts/list_changed`, etc.). The client opts in to each notification
  type explicitly.
- Out of scope for this implementation — we don't need it for the
  confirmation paradigm.

### 2.9 Error code change (SEP-2164)

- "Resource not found" moves from `-32002` (custom) → `-32602` (JSON-RPC
  Invalid Params). We don't currently emit `-32002`, so no change for us.

### 2.10 URL-mode elicitation (SEP-1036)

Form-mode elicitation is what we use today. URL-mode elicitation:

```ts
interface ElicitRequestURLParams {
  mode: 'url'
  url: string
  elicitationId: string
  message: string
}
```

- The client opens `url` in the user's browser; the in-band response is one
  of `accept | decline | cancel` with no `content` (acceptance just means
  "I navigated").
- The server can complete the out-of-band flow and send
  `notifications/elicitation/complete` with the `elicitationId` when done.
- A capability declaration looks like `capabilities.elicitation: { form: {}, url: {} }`.
- Out of scope for v1 of this implementation. We mark it as deferred and
  emit only `mode: "form"` for now.

## 3. What the existing pipeline already gets right

Before specifying the parallel pipeline, the existing one already does
several things that the `2026-07-28` flow assumes:

- Per-token rate limiting in `rate-limiter.ts` — survives.
- Auth + bearer-token plumbing in `request-utils.ts` — survives.
- Per-token capability cache (`CapabilityStore`, `mcp:client-caps:*`) —
  partly survives: in the new protocol, capabilities arrive per-request via
  `_meta`, so the cache becomes a read-through optimization, not a source of
  truth. Less critical, but harmless to keep.
- `requestConfirmation()` runtime in `confirmation-runtime.ts` — survives,
  but the implementation under the hood swaps for the new protocol (see §5.3).
- `ToolCatalog` + `ToolExecutor` + the tool handler signature — survive
  unchanged. The handler API doesn't know which protocol delivered the call.
- The codegen output in `generated/*.ts` — unchanged. The `confirmation:`
  YAML field's emit stays the same.

What does NOT survive when we serve a `2026-07-28` request:

- The `SessionResponseBus` (`InMemory` and `RedisPolling` impls): the new
  protocol assumes any server instance can handle the retry from
  `requestState` alone. No cross-pod await needed.
- The SSE upgrade race in `dispatchToolsCallWithMaybeSse` and
  `finalizeSseResponse`: the new protocol responds with plain JSON whether
  or not the tool elicits.
- `ElicitBinding` + `firstElicit` race + `createSseResponse`: same reason.
- The `classifyBody` JSON-RPC-response routing in `streamable-handler.ts`:
  there are no separate response POSTs in the new protocol; every POST is a
  fresh `tools/call`.

These all stay in the codebase. They're the implementation of the
`2025-06-18` pipeline, which we still serve.

## 4. Architecture — version-dispatched pipeline

The split happens at one point: the streamable handler picks a pipeline
based on the negotiated protocol version, and from then on the two
pipelines do not share code on the request hot path.

```text
                  POST /mcp
                      │
                      ▼
              StreamableMcpHandler.fetch
                      │
        ┌─────────────┴─────────────┐
        │                           │
   parseProtocolVersion        (no version /
   from headers + _meta         old initialize)
        │                           │
        ▼                           ▼
   ┌────────────┐              ┌────────────┐
   │ legacy     │              │ legacy     │
   │ pipeline   │              │ pipeline   │
   │ (2025-06-18│              │ (initialize│
   │  default)  │              │  handshake)│
   └────────────┘              └────────────┘
        ▲
        │ same dispatcher we ship today
        │
              POST /mcp + MCP-Protocol-Version: 2026-07-28
                      │
                      ▼
              StreamableMcpHandler.fetch
                      │
                      ▼
              v2026 pipeline (new)
                      │
                      ▼
            McpDispatcher2026.handleRequest
                      │
        ┌─────────────┼─────────────────────────────┐
        │             │                             │
        ▼             ▼                             ▼
   server/discover  tools/call (initial)     tools/call (retry with
                       │                       inputResponses + requestState)
                       ▼                             │
                  Run tool handler                   ▼
                       │                       Decode + validate requestState
                       │                       Reconstruct elicit-completed context
                       ▼                             │
                  If elicit not needed →             ▼
                  return resultType: 'complete'  Run tool handler
                  + content                          │
                       │                             ▼
                  If elicit needed →            If still needs input →
                  return InputRequiredResult    return InputRequiredResult
                  with inputRequests + new      with cumulative state
                  requestState                       │
                                                If complete →
                                                return resultType: 'complete'
```

### 4.1 Pipeline selection

The version is read from the `MCP-Protocol-Version` HTTP header (preferred,
because routing infrastructure may use it). The body's
`_meta["io.modelcontextprotocol/protocolVersion"]` must match — if it doesn't,
reject with `400`. If the header is absent, treat as `2025-06-18` (the legacy
pipeline is the unambiguous default; this avoids breaking every client that
ships today). Clients that explicitly opt into the legacy pipeline by sending
`MCP-Protocol-Version: 2025-06-18` are honored as legacy — there's no future
in which we'd want to interpret the header differently.

```ts
function selectPipeline(req: Request): 'legacy' | 'v2026' {
  const headerVersion = req.headers.get('MCP-Protocol-Version')
  if (!headerVersion) return 'legacy'
  if (headerVersion === '2026-07-28') return 'v2026'
  if (headerVersion === '2025-06-18') return 'legacy' // explicit opt-in
  // Future versions: extend the table.
  return 'legacy'
}
```

### 4.2 Where the v2026 pipeline lives

New files, all under `services/mcp/src/hono/v2026/`:

```text
v2026/
  README.md                     // points at this spec
  dispatcher.ts                 // McpDispatcher2026
  request-meta.ts               // parse + validate _meta + headers; reject bad shapes
  request-state.ts              // encode/decode + sign/verify requestState
  input-required-result.ts      // build InputRequiredResult payloads
  input-responses.ts            // decode inputResponses from retry params
  discover.ts                   // server/discover handler
  errors.ts                     // -32003, -32004 typed errors + status codes
  metrics.ts                    // v2026-specific Prometheus metrics
```

We don't touch the existing `dispatcher.ts`, `request-context.ts`,
`elicit-binding.ts`, `session-bus/`, `sse-response.ts`, or
`streamable-handler.ts` other than to add the pipeline branch.

### 4.3 Per-request `_meta` parsing

`request-meta.ts` exposes a single function:

```ts
interface V2026RequestMeta {
  protocolVersion: '2026-07-28'
  clientInfo: { name: string; version: string }
  clientCapabilities: ClientCapabilities
  logLevel?: LoggingLevel
}

function parseV2026Meta(req: Request, body: JSONRPCRequest): V2026RequestMeta
```

Errors:

- Missing required `_meta` field → `INVALID_PARAMS` (`-32602`), HTTP `400`.
- Header / body version mismatch → `INVALID_PARAMS`, HTTP `400`.
- Unsupported version → `UNSUPPORTED_PROTOCOL_VERSION` (`-32004`), HTTP `400`,
  with `data.supported` listing the versions we know about.

### 4.4 `requestState` encoding

We use an HMAC-SHA256 signed JWT-compact-format token with these claims:

```ts
interface RequestStateClaims {
  sub: string // userHash — binds state to the authenticated principal
  iat: number // issued at — unix seconds
  exp: number // expiry — iat + 600 (10 min)
  nonce: string // 128-bit random — prevents trivial replay across users
  tool: string // tool name — guards against cross-tool state injection
  round: number // monotonic counter — capped to prevent unbounded loops (see §4.4.1)
  payload: unknown // tool-author-supplied state (re-validated as untrusted)
}
```

Signing key:

- **Dedicated to MCP.** New env var `MCP_REQUEST_STATE_SIGNING_KEY` (32+ bytes
  of random entropy). Not shared with Django's `SECRET_KEY` — the blast radius
  for a key compromise stays local to MCP, and rotating one service does not
  invalidate the other's signed material.
- **Required in production.** The Hono entrypoint refuses to start when
  `NODE_ENV === 'production'` and the env var is missing, empty, or shorter
  than 32 bytes. Mirrors the Django `SECRET_KEY` guard at
  `posthog/settings/access.py:69-76`.
- **Rotatable** via an optional secondary key: support
  `MCP_REQUEST_STATE_SIGNING_KEY_OLD` whose signatures we still accept on
  verify but never use for signing. Lets us roll a new key forward without
  invalidating every in-flight retry.

We deliberately do NOT encrypt — the payload's confidentiality is the tool
author's responsibility, and HMAC is enough for the integrity bind. If a
specific tool needs confidentiality (e.g. it stores partially-collected
credentials in `requestState`), it encrypts the `payload` field itself
before handing it to the framework.

#### 4.4.1 Round counter (multi-round cap)

Tool handlers can issue an `InputRequiredResult` more than once for the same
logical tool call (e.g. an Azure-DevOps-style flow where the first answer
unlocks a second prompt). Each round increments `round` in `requestState`.
The dispatcher enforces a hard cap: when an incoming retry carries
`round >= MAX_REQUEST_STATE_ROUNDS`, decode succeeds but
`handleToolsCall` returns a typed error instead of re-invoking the handler.
The client receives a `complete` result with `isError: true` and a message
explaining the cap.

- `MAX_REQUEST_STATE_ROUNDS = 10` — a hard-coded constant in
  `v2026/constants.ts`, not configurable via env. The number is generous
  enough for legitimate multi-step flows (ADO custom-rules style chains rarely
  exceed 3–4 prompts), tight enough to bound the cost of a buggy or
  adversarial loop.
- Tools approaching the cap should redesign their flow to collect inputs in
  fewer rounds — combining prompts, using nested schemas, or persisting state
  to their own backend if the data is large.

On decode:

- Verify signature. Failure → `INVALID_PARAMS` with message
  `"requestState signature invalid"`. Don't reveal whether the key, nonce,
  or expiry was the cause.
- Verify `exp > now`. Expired → tell the client to start over (omit
  `requestState` from the next `InputRequiredResult`).
- Verify `sub === currentUserHash`. Mismatch → `INVALID_PARAMS`. This is the
  cross-user replay defense SEP-2322 mandates.
- Verify `tool === incoming tool name`. Mismatch → `INVALID_PARAMS`.

We deliberately do NOT encrypt — the payload's confidentiality is the tool
author's responsibility, and HMAC is enough for the integrity bind. If a
specific tool needs confidentiality (e.g. it stores partially-collected
credentials in `requestState`), it encrypts the `payload` field itself
before handing it to the framework.

### 4.5 Tool handler API surface

The existing `ToolBase['handler']` signature stays:

```ts
type Handler<Schema, Result> = (context: Context, params: z.infer<Schema>) => Promise<Result>
```

We extend `Context` (additively, optional fields) with the new-protocol APIs.
A tool can opt into the new behavior; tools that don't opt in continue to
work via the existing `context.elicit?` API in the legacy pipeline only.

```ts
interface Context {
  // ... existing fields ...

  /**
   * 2025-06-18 only — sends elicitation/create over SSE and awaits via the
   * session bus. Undefined when the client did not advertise the capability,
   * or when the pipeline is v2026.
   */
  elicit?: ElicitFn

  /**
   * Universal: works in BOTH pipelines. The runtime picks the right
   * underlying mechanism. The handler writes straight-line code; the
   * v2026 pipeline rebuilds the call frame from `requestState` on retry.
   */
  requestInput?: RequestInputFn
}

interface RequestInputFn {
  <TSchema extends ElicitRequestFormParams['requestedSchema']>(params: {
    key: string
    message: string
    requestedSchema: TSchema
  }): Promise<ElicitResult>
}
```

`requestInput` is the universal seam. Inside it:

- **Legacy pipeline:** delegates to `context.elicit?.()` (the existing bus
  flow). If `elicit` is missing, throws `ElicitationNotSupportedError`. No
  behavior change.
- **v2026 pipeline:** on the FIRST call, throws a special internal
  `InputRequiredSignal` carrying the input request + the state to encode.
  The dispatcher catches it, builds `InputRequiredResult`, encodes
  `requestState`, returns. On the RETRY (when `inputResponses[key]` is
  present in the incoming `_meta`-extended params), `requestInput` returns
  the matching response synchronously without re-invoking the client.

The signal pattern lets tool authors keep writing straight-line code:

```ts
const result = await context.requestInput({
  key: 'confirm',
  message: 'Enable 2FA?',
  requestedSchema: { type: 'object', properties: {} },
})
if (result.action !== 'accept') return refusal()
// proceed
```

The runtime decides whether to suspend (throw the signal) or resume (return
the cached response from inputResponses). The codegen layer in PR #60195's
`requestConfirmation()` is updated to call `requestInput` instead of
`elicit` — single change, both pipelines benefit.

### 4.6 `server/discover`

A new method on `McpDispatcher2026`:

```ts
interface DiscoverResult {
  supportedVersions: string[] // ["2025-06-18", "2026-07-28"]
  capabilities: ServerCapabilities
  serverInfo: { name: 'PostHog'; version: string }
  instructions?: string
}
```

This is also what we recommend clients call **before** any other RPC.
Existing legacy `initialize` handler stays exactly as is for the legacy
pipeline.

## 5. File-level deltas

### 5.1 `streamable-handler.ts` — version-dispatch one branch

```ts
fetch = async (c: HonoCtx): Promise<Response> => {
  // ... unchanged auth + rate limit ...

  const pipeline = selectPipeline(c.req.raw)
  if (pipeline === 'v2026') {
    return await this.dispatcherV2026.handleRequest(c.req.raw, auth.props)
  }
  return await this.dispatcher.handleRequest(c.req.raw, auth.props)
}
```

`selectPipeline` lives in `v2026/request-meta.ts`. One new branch; nothing
else changes.

### 5.2 `dispatcher.ts` — unchanged

The legacy dispatcher is the implementation of the `2025-06-18` pipeline.
We don't modify it. Adding `v2026/dispatcher.ts` is a fresh implementation,
no shared base class. The cost of duplication is small (the legacy
dispatcher is ~400 lines) and the value of isolation is high: we can
delete `dispatcher.ts` cleanly when the legacy protocol is retired.

### 5.3 `confirmation-runtime.ts` — gain a universal seam

Today:

```ts
export async function requestConfirmation(context, params, options) {
    if (!context.elicit) return noElicitOutcome(...)
    const result = await context.elicit({ message, requestedSchema })
    // ...
}
```

After:

```ts
export async function requestConfirmation(context, params, options) {
    if (!context.requestInput) return noElicitOutcome(...) // both pipelines reach this if no capability
    const result = await context.requestInput({
        key: 'confirm',
        message,
        requestedSchema: { type: 'object', properties: {} },
    })
    // ... same accept / decline / cancel branches ...
}
```

`requestInput` is implemented in both `RequestContext` (legacy) and
`V2026RequestContext` (new). The legacy one delegates to `context.elicit`
under the hood — pure refactor, no behavior change.

### 5.4 New: `v2026/dispatcher.ts`

```ts
class McpDispatcher2026 {
  async handleRequest(req: Request, props: RequestProperties): Promise<Response> {
    const body = await parseBody(req)
    const meta = parseV2026Meta(req, body) // throws → error response

    // server/discover is the only RPC that doesn't carry an MCP-Name header,
    // and is the only one for which inputResponses are nonsense.
    if (body.method === 'server/discover') {
      return handleDiscover(meta, this.serverCapabilities)
    }

    // Tools/call (initial OR retry — same dispatch path).
    if (body.method === 'tools/call') {
      return await this.handleToolsCall(body, meta, props)
    }

    // Other RPCs (tools/list, prompts/get, resources/read, ping).
    return await this.handleOther(body, meta, props)
  }

  private async handleToolsCall(body, meta, props): Promise<Response> {
    // Decode requestState if present. Reject on signature / sub / exp / tool
    // mismatch.
    const priorState = body.params.requestState
      ? this.requestStateCodec.decode(body.params.requestState, props.userHash, body.params.name)
      : undefined

    // Build a v2026 Context whose `requestInput` knows about
    // inputResponses + priorState.
    const context = await this.buildContext(props, body, meta, priorState)

    try {
      const result = await this.toolExecutor.handleToolCall(body.params, props, state, context)
      return jsonRpcCompleteResult(body.id, result)
    } catch (signal) {
      if (signal instanceof InputRequiredSignal) {
        const nextState = this.requestStateCodec.encode({
          sub: props.userHash,
          tool: body.params.name,
          payload: signal.statePayload,
        })
        return jsonRpcInputRequiredResult(body.id, signal.inputRequests, nextState)
      }
      throw signal
    }
  }
}
```

### 5.5 New: `v2026/input-required-result.ts`

Builds the response body:

```ts
function jsonRpcInputRequiredResult(id: string | number, inputRequests: InputRequests, requestState: string): Response {
  const body = {
    jsonrpc: '2.0' as const,
    id,
    result: {
      resultType: 'input_required' as const,
      inputRequests,
      requestState,
    },
  }
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}
```

### 5.6 New: `v2026/request-state.ts`

Tiny module wrapping `jose` or `node:crypto` for HMAC signing:

```ts
class RequestStateCodec {
  encode(claims: RequestStateClaims): string
  decode(token: string, expectedUser: string, expectedTool: string): RequestStateClaims
}
```

Errors throw structured `RequestStateError` subclasses
(`SignatureInvalid`, `Expired`, `UserMismatch`, `ToolMismatch`) that the
dispatcher translates to JSON-RPC errors.

### 5.7 New: `v2026/discover.ts`

Static-ish response. Reads from a constant + the existing instructions
builder.

### 5.8 New: `tools/types.ts` — `Context.requestInput`

Add the optional field. JSDoc explains the dual-pipeline semantics.

### 5.9 New: `v2026/request-context.ts`

Mirrors the existing `RequestContext` but its `requestInput` implementation
is the throw-`InputRequiredSignal` / consume-from-`inputResponses` logic.
The `Context.elicit` field is omitted (always `undefined`) so any tool that
relied on the legacy API gets `undefined` and falls back via the
`if (context.requestInput)` check that the universal `requestConfirmation`
runtime uses.

### 5.10 New metrics

In `v2026/metrics.ts`:

- `mcp_v2026_requests_total{outcome=complete|input_required|error}` — counter,
  every dispatched `tools/call` request on the v2026 pipeline.
- `mcp_v2026_request_state_decode_total{result=ok|bad_signature|expired|user_mismatch|tool_mismatch|rounds_exceeded|malformed}` —
  counter, observability for every decode attempt including failure modes.
- `mcp_v2026_request_state_expired_total` — counter, dedicated time-series
  for the expiry case so the 10-minute TTL can be tuned from a single
  signal. A sustained non-zero rate means the window is too tight for real
  user latency; alert from this counter and adjust `REQUEST_STATE_TTL_SECONDS`
  if it fires.
- `mcp_v2026_input_required_round_trips` — histogram of how many rounds a
  single logical tool-call took before completing.

The existing `mcp_session_bus_*` and `mcp_client_capability_cache_*`
counters keep working for legacy traffic. Dashboards stay valid by
filtering on a new `pipeline` label that we add to existing counters where
practical.

### 5.11 No change

- `dispatcher.ts`, `request-context.ts`, `elicit-binding.ts`,
  `session-bus/`, `sse-response.ts`, `streamable-handler.ts` (other than
  the one new branch), `capability-store.ts`.
- `generated/*.ts` — codegen output unchanged.
- `generate-tools.ts` — codegen logic unchanged (the gate calls
  `requestConfirmation` which calls `requestInput` which the runtime
  resolves to the right backend).
- All YAML.
- All tests for the existing pipeline.

## 6. Confirmation paradigm impact

The whole point of PR #60195 was to make destructive tools declarative.
We preserve that. The `confirmation:` YAML block continues to work
unchanged. Under the hood:

| Pipeline     | Client lacks elicit support | Client supports elicit, single round | Multi-round elicit (future)                |
| ------------ | --------------------------- | ------------------------------------ | ------------------------------------------ |
| `2025-06-18` | `on_no_elicit` policy fires | SSE + bus round-trip                 | Multiple elicits parked on same bus        |
| `2026-07-28` | `on_no_elicit` policy fires | One `InputRequiredResult` + retry    | Native — extra rounds reuse `requestState` |

Tool author writes the same YAML; the runtime adapts.

## 7. Testing strategy

### 7.1 Unit tests (TDD-friendly, no live infra)

- `v2026/request-meta.test.ts` — every required/optional `_meta` field
  permutation; header/body mismatch; unsupported version path.
- `v2026/request-state.test.ts` — signature roundtrip; tampering detection;
  expiry; user-mismatch; tool-mismatch; rotating signing key.
- `v2026/dispatcher.test.ts` — initial call returning `complete`; initial
  call throwing `InputRequiredSignal` → `InputRequiredResult` with the
  encoded `requestState`; retry with valid `inputResponses` →
  `complete`; retry with stale `requestState` → `INVALID_PARAMS`.
- `v2026/discover.test.ts` — response shape; correct list of supported
  versions.

### 7.2 Integration tests

Add cases to the existing `mcp-protocol.test.ts` integration suite under
a `MCP protocol (Hono) — v2026` describe:

- Initialize: no `initialize` RPC; first call is `server/discover`. Returns
  expected capabilities.
- A tool with `confirmation:` set to `message: "Proceed?"`,
  `on_no_elicit: deny`:
  - Client declares `capabilities.elicitation: {}` → first call returns
    `InputRequiredResult`; retry with `inputResponses.confirm =
{action: "accept"}` → `complete` with the API result.
  - Client does NOT declare elicitation → first call returns `complete`
    with the `on_no_elicit` denial message.
- A tool that elicits twice (multi-round): two `InputRequiredResult` cycles,
  intermediate `requestState` correctly carries the first answer through.
- Cross-pod simulation: run two `createApp` instances against the same
  Redis, send the initial call to A, the retry to B → the retry succeeds
  because `requestState` is self-contained.

### 7.3 Adversarial tests

- Replay: client sends `requestState` issued for user X under user Y's
  auth → rejected.
- Tampering: flip a bit in the JWT signature → rejected.
- Expiry: clock advance past `exp` → rejected.
- Truncation: client omits `requestState` on retry → server treats as fresh
  call (no prior state) and the tool's `requestInput` re-issues the prompt.
- Wrong tool: client sends `requestState` issued for `tool-A` but calls
  `tool-B` → rejected.
- Oversize `inputResponses`: ensure rate limiter + body-size guards apply.

### 7.4 Manual / Inspector

Once Claude Code / Inspector ship `2026-07-28` support (not before final
release), drive an end-to-end with the temp `debug-mcp-ui-apps` scaffold
the way we did for the legacy pipeline.

## 8. Rollout plan

1. **Land this spec.** No code. Lets reviewers debate the
   `requestState` design and the `requestInput` signal pattern before any
   line of code is written.
2. **PR 1 — scaffolding.** Add `v2026/` directory with `dispatcher.ts`
   stub (returns `405` for everything), `request-meta.ts`, `request-state.ts`,
   `errors.ts`, `metrics.ts`. Tests for the codec and meta parser. No
   wiring to `streamable-handler` yet.
3. **PR 2 — minimum viable pipeline.** Wire `streamable-handler` to dispatch
   on the protocol version. Implement `server/discover`, `tools/list`,
   `tools/call` (no elicit yet, just pass-through). Integration tests
   confirming a legacy client still works and a v2026 client gets a
   complete result for a non-elicit tool.
4. **PR 3 — `requestInput` + `InputRequiredResult`.** Add the signal pattern,
   refactor `requestConfirmation` to call `requestInput`. Integration tests
   for the single-round elicit flow. The confirmation paradigm now works on
   both protocols end-to-end.
5. **PR 4 — multi-round + adversarial.** Multi-round `requestState` chains
   and the full adversarial suite. Update the implementing-mcp-tools skill.

Total: ~4 PRs. PR 1 is the only one that could land before final spec; the
rest should wait for a Claude Code client we can test against.

## 9. Resolved decisions

These were open in the first draft; recording the resolution here so
reviewers see the rationale alongside the spec.

- **Signing key:** dedicated MCP key, env var `MCP_REQUEST_STATE_SIGNING_KEY`,
  refuse-to-start in production if missing or < 32 bytes. Not shared with
  Django's `SECRET_KEY` — independent blast radius and independent rotation.
  Secondary `MCP_REQUEST_STATE_SIGNING_KEY_OLD` accepted on verify only,
  enabling zero-downtime key rotation.
- **`exp` window:** 10 minutes, fixed at `REQUEST_STATE_TTL_SECONDS = 600`.
  Tracked via `mcp_v2026_request_state_expired_total` for tuning.
- **Multi-round step counter:** `round` claim in `requestState`, hard cap
  `MAX_REQUEST_STATE_ROUNDS = 10` as a source constant (no env override).
  Bounds buggy / adversarial loops without restricting realistic multi-step
  flows.
- **Explicit legacy opt-in:** `MCP-Protocol-Version: 2025-06-18` is accepted
  as an explicit legacy route in the version-dispatch table.

## 10. Deferred follow-ups

- **`server/discover` caching headers** — the response is essentially static
  per build, but we ship without `Cache-Control` and add it later if traffic
  patterns make it worthwhile.
- **URL-mode elicitation (SEP-1036)** — the 2FA tool is the obvious candidate
  for a future iteration (browser-driven step-up reauth via the PostHog UI).
  Not on the v1 path.

## Appendix A: Wire-format cheat sheet

### Initial `tools/call` (no elicit needed)

```http
POST /mcp HTTP/1.1
Content-Type: application/json
Authorization: Bearer phx_...
MCP-Protocol-Version: 2026-07-28
Mcp-Method: tools/call
Mcp-Name: get_weather

{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "get_weather",
    "arguments": {"location": "NYC"},
    "_meta": {
      "io.modelcontextprotocol/protocolVersion": "2026-07-28",
      "io.modelcontextprotocol/clientInfo": {"name": "claude-code", "version": "2.1.149"},
      "io.modelcontextprotocol/clientCapabilities": {}
    }
  }
}
```

→

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "resultType": "complete",
    "content": [{ "type": "text", "text": "72°F partly cloudy" }],
    "isError": false
  }
}
```

### `tools/call` that needs confirmation

Initial response:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "resultType": "input_required",
    "inputRequests": {
      "confirm": {
        "method": "elicitation/create",
        "params": {
          "mode": "form",
          "message": "Enable enforce 2FA on organization acme?",
          "requestedSchema": { "type": "object", "properties": {} }
        }
      }
    },
    "requestState": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOi..."
  }
}
```

Client retries with a NEW `id`:

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/call",
  "params": {
    "name": "organization-enforce-2fa-update",
    "arguments": { "orgId": "019e2357-bad3", "enforce_2fa": true },
    "inputResponses": {
      "confirm": { "action": "accept" }
    },
    "requestState": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOi...",
    "_meta": {
      "io.modelcontextprotocol/protocolVersion": "2026-07-28",
      "io.modelcontextprotocol/clientInfo": {
        "name": "claude-code",
        "version": "2.1.149"
      },
      "io.modelcontextprotocol/clientCapabilities": {
        "elicitation": { "form": {} }
      }
    }
  }
}
```

Server completes:

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "result": {
    "resultType": "complete",
    "content": [{ "type": "text", "text": "Enforce 2FA enabled for organization acme." }],
    "isError": false
  }
}
```

## References

- [SEP-2322 (MRTR)](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2322)
- [SEP-2260 (associate server requests with client requests)](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2260)
- [SEP-2575 (stateless MCP / no `initialize`)](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2575)
- [SEP-2567 (sessionless MCP / no `Mcp-Session-Id`)](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2567)
- [SEP-2243 (HTTP header standardization)](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2243)
- [SEP-2164 (resource-not-found error code)](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2164)
- [SEP-1036 (URL-mode elicitation)](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/1036)
- [RC blog post](https://blog.modelcontextprotocol.io/posts/2026-07-28-release-candidate/)
