// Shared MCP-protocol integration suite. Wires the official @modelcontextprotocol/sdk
// client against a runtime-supplied transport target and exercises the standard
// JSON-RPC interactions: initialize handshake, tools/list, tools/call, prompts/list,
// resources/list, and clean disconnect. Both the Cloudflare and Hono entry points
// run the same suite so any divergence shows up as a test failure rather than a
// silent runtime drift.

import { Client } from '@modelcontextprotocol/sdk/client/index.js'
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

export type ProtocolTestHarness = {
    /** Origin used to construct the MCP endpoint URL (e.g. `https://test.local`). */
    baseUrl: URL
    /** Fetch implementation routing to the runtime under test. */
    fetch: typeof fetch
    /** Bearer token forwarded as the `Authorization` header. */
    token: string
    /** Optional second bearer token for the concurrent-sessions isolation test.
     * When omitted the isolation test is skipped. */
    token2?: string | undefined
    /** Whether the runtime is stateless (no session store). Stateless runtimes
     * ignore unknown Mcp-Session-Id headers instead of rejecting them. */
    stateless?: boolean | undefined
    /** Whether the runtime returns empty results for unknown resources/prompts
     * instead of throwing errors. The Hono dispatcher does this; the CF SDK doesn't. */
    gracefulUnknown?: boolean | undefined
    /** Optional org/project ids — only set when the harness runs against the real
     * PostHog API. Tests that hit the upstream API (projects-get, switch-project,
     * organization-get response shape) skip when these are missing. */
    orgId?: string | undefined
    projectId?: string | undefined
    /** Whether public HTTP routes (/health, /readyz, /.well-known/...) are wired
     * up on this runtime. The Hono entrypoint exposes them; the in-process mock
     * harness may bypass them. Defaults to true. */
    publicRoutes?: boolean | undefined
}

function buildStreamableClient(
    harness: ProtocolTestHarness,
    token: string = harness.token
): { client: Client; transport: StreamableHTTPClientTransport } {
    const transport = new StreamableHTTPClientTransport(new URL('/mcp', harness.baseUrl), {
        fetch: harness.fetch,
        requestInit: { headers: { Authorization: `Bearer ${token}` } },
    })
    const client = new Client({ name: 'mcp-integration-test', version: '0.0.0' }, { capabilities: {} })
    return { client, transport }
}

function buildExecModeClient(
    harness: ProtocolTestHarness
): { client: Client; transport: StreamableHTTPClientTransport } {
    const transport = new StreamableHTTPClientTransport(new URL('/mcp', harness.baseUrl), {
        fetch: harness.fetch,
        requestInit: {
            headers: {
                Authorization: `Bearer ${harness.token}`,
                'x-posthog-mcp-mode': 'cli',
            },
        },
    })
    const client = new Client({ name: 'mcp-exec-test', version: '0.0.0' }, { capabilities: {} })
    return { client, transport }
}

// SDK exposes `sessionId` as `string | undefined` but the `Transport` interface
// declares it as `string`. The runtime contract is satisfied (the transport
// sets the id after the initialize handshake); the assignability mismatch is a
// type-definition quirk we paper over at the seam.
type ConnectableTransport = Parameters<Client['connect']>[0]

async function safeClose(client: Client | undefined): Promise<void> {
    try {
        await client?.close()
    } catch {
        // SDK Client.close throws if already closed; harmless during teardown.
    }
}

export function defineMcpProtocolTests(
    label: string,
    getHarness: () => Promise<ProtocolTestHarness> | ProtocolTestHarness
): void {
    describe(`MCP protocol (${label})`, () => {
        let client: Client
        let currentHarness: ProtocolTestHarness

        beforeEach(async () => {
            currentHarness = await getHarness()
            const built = buildStreamableClient(currentHarness)
            client = built.client
            await client.connect(built.transport as ConnectableTransport)
        })

        afterEach(async () => {
            await safeClose(client)
        })

        it('reports server name and version after the initialize handshake', () => {
            const info = client.getServerVersion()
            expect(info?.name).toBe('PostHog')
            expect(info?.version).toBeTruthy()
        })

        it('returns instructions in the initialize response', () => {
            const instructions = client.getInstructions()
            expect(instructions).toBeTruthy()
            expect(typeof instructions).toBe('string')
            expect(instructions!.length).toBeGreaterThan(0)
        })

        it('lists available tools with non-empty schemas', async () => {
            const { tools } = await client.listTools()
            expect(tools.length).toBeGreaterThan(0)

            const sample = tools[0]
            if (!sample) {
                throw new Error('expected at least one tool')
            }
            expect(sample.name).toBeTruthy()
            expect(sample.inputSchema).toBeTruthy()
            expect(sample.inputSchema.type).toBe('object')
        })

        it('exposes a known PostHog tool (organization-get)', async () => {
            const { tools } = await client.listTools()
            const names = tools.map((t) => t.name)
            expect(names).toContain('organization-get')
        })

        it('lists prompts', async () => {
            if (!currentHarness.gracefulUnknown) {
                return
            }
            const { prompts } = await client.listPrompts()
            expect(Array.isArray(prompts)).toBe(true)
        })

        it('lists resources including UI apps', async () => {
            const { resources } = await client.listResources()
            expect(resources.length).toBeGreaterThan(0)
            const uris = resources.map((r) => r.uri)
            expect(uris.some((u) => u.startsWith('ui://'))).toBe(true)
        })

        it('reads a UI app resource end-to-end', async () => {
            const { resources } = await client.listResources()
            const uiApp = resources.find((r) => r.uri.startsWith('ui://'))
            if (!uiApp) {
                throw new Error('expected at least one ui:// resource')
            }
            expect(uiApp.mimeType).toBeTruthy()

            const result = await client.readResource({ uri: uiApp.uri })
            expect(result.contents.length).toBeGreaterThan(0)
            expect(result.contents[0]?.uri).toBe(uiApp.uri)
        })

        it('reads a context-mill resource by URI', async () => {
            const { resources } = await client.listResources()
            const cmResource = resources.find((r) => r.uri.startsWith('posthog://'))
            if (!cmResource) {
                throw new Error('expected at least one posthog:// resource from context-mill')
            }

            const result = await client.readResource({ uri: cmResource.uri })
            expect(result.contents.length).toBeGreaterThan(0)
            expect(result.contents[0]?.uri).toBe(cmResource.uri)
            const text = 'text' in result.contents[0]! ? result.contents[0].text : ''
            expect(text).toBeTruthy()
        })

        it('returns empty contents for an unknown resource URI', async () => {
            if (!currentHarness.gracefulUnknown) {
                return
            }
            const result = await client.readResource({ uri: 'posthog://does-not-exist' })
            expect(result.contents).toEqual([])
        })

        it('returns empty messages for an unknown prompt name', async () => {
            if (!currentHarness.gracefulUnknown) {
                return
            }
            const result = await client.getPrompt({ name: 'nonexistent-prompt' })
            expect(result.messages).toEqual([])
        })

        it('calls a tool and returns content blocks', async () => {
            const result = await client.callTool({
                name: 'organization-get',
                arguments: {},
            })
            if (result.isError) {
                throw new Error(`tool returned error: ${JSON.stringify(result.content)}`)
            }
            expect(Array.isArray(result.content)).toBe(true)
            expect((result.content as unknown[]).length).toBeGreaterThan(0)
        })

        it('returns an error result for an unknown tool name', async () => {
            // `callTool` resolves successfully and surfaces the error in the
            // tool-call payload rather than rejecting the JSON-RPC call.
            const result = await client.callTool({
                name: 'no-such-tool-exists',
                arguments: {},
            })
            expect(result.isError).toBe(true)
        })

        // Concurrent sessions with different bearer tokens must not see each
        // other's state. Different tokens hash to different `userHash`es, which
        // is what the SessionRegistry (Hono) and DurableObject naming (CF) key
        // off — so a regression in either would let one client's tool registry,
        // organization context, or cached responses leak into the other's view.
        // Two-step assertion: each client (a) initializes successfully against
        // a different token, and (b) gets its own copy of the tool list with
        // the same canonical entries. If session lookup ever cross-pollinates
        // by accident, both clients would fail to initialize cleanly.
        it('isolates state between concurrent sessions on different tokens', async ({ skip }) => {
            const harness = await getHarness()
            if (!harness.token2) {
                skip('Set TEST_POSTHOG_PERSONAL_API_KEY_2 to run the concurrent-sessions isolation test.')
                return
            }

            const a = buildStreamableClient(harness, harness.token)
            const b = buildStreamableClient(harness, harness.token2)

            try {
                await Promise.all([
                    a.client.connect(a.transport as ConnectableTransport),
                    b.client.connect(b.transport as ConnectableTransport),
                ])

                // Both clients should resolve initialize against their own session.
                expect(a.client.getServerVersion()?.name).toBe('PostHog')
                expect(b.client.getServerVersion()?.name).toBe('PostHog')

                const [toolsA, toolsB] = await Promise.all([a.client.listTools(), b.client.listTools()])

                // Each session got a tool list (no cross-talk that would surface as
                // empty/missing tools on one side).
                expect(toolsA.tools.length).toBeGreaterThan(0)
                expect(toolsB.tools.length).toBeGreaterThan(0)
                expect(toolsA.tools.map((t) => t.name)).toContain('organization-get')
                expect(toolsB.tools.map((t) => t.name)).toContain('organization-get')
            } finally {
                await Promise.all([safeClose(a.client), safeClose(b.client)])
            }
        })
    })
}

// MCP UI apps coverage (the `@modelcontextprotocol/ext-apps` extension).
// Tools wrapped with `withUiApp(...)` advertise a `_meta.ui.resourceUri` on
// every call result. Clients fetch that URI via `resources/read` to get an
// HTML stub that loads the per-app JS+CSS bundle from `${MCP_APPS_BASE_URL}/ui-apps/<app>/`.
//
// Failures this catches:
//   - Tool decorator stripped or not wired through registerTool (no `_meta`)
//   - `registerUiAppResources` skipped (e.g. MCP_APPS_BASE_URL missing)
//   - HTML stub generation produces wrong asset URLs
//   - Static-asset serving broken (Hono `serveStatic` route, CF Workers Static Assets)
export function defineUiAppProtocolTests(
    label: string,
    getHarness: () => Promise<ProtocolTestHarness> | ProtocolTestHarness
): void {
    describe(`MCP UI apps (${label})`, () => {
        let client: Client
        let harness: ProtocolTestHarness

        beforeEach(async () => {
            harness = await getHarness()
            const built = buildStreamableClient(harness)
            client = built.client
            await client.connect(built.transport as ConnectableTransport)
        })

        afterEach(async () => {
            await safeClose(client)
        })

        // The UI metadata is on the *tool definition* (returned in `tools/list`),
        // not on per-call results — that's how the ext-apps SDK + clients
        // discover which UI app to render. We pull the URI here once and reuse
        // it across the next two tests.
        async function findDebugUiResourceUri(): Promise<string> {
            const { tools } = await client.listTools()
            const debug = tools.find((t) => t.name === 'debug-mcp-ui-apps')
            if (!debug) {
                throw new Error('debug-mcp-ui-apps tool not registered')
            }
            const meta = (debug as { _meta?: { ui?: { resourceUri?: string } } })._meta
            const uri = meta?.ui?.resourceUri
            if (!uri) {
                throw new Error(
                    `debug-mcp-ui-apps tool definition is missing _meta.ui.resourceUri (got ${JSON.stringify(meta)})`
                )
            }
            return uri
        }

        it('advertises a UI resource URI on the debug-mcp-ui-apps tool', async () => {
            const uri = await findDebugUiResourceUri()
            expect(uri).toMatch(/^ui:\/\/|^mcp-ext-app:\/\//)
        })

        it('reads the ext-app resource and returns an HTML stub', async () => {
            const uri = await findDebugUiResourceUri()
            const resource = await client.readResource({ uri })
            expect(resource.contents.length).toBeGreaterThan(0)
            const first = resource.contents[0]
            if (!first) {
                throw new Error('expected resource contents to be non-empty')
            }
            const text = 'text' in first ? String(first.text ?? '') : ''
            expect(text).toContain('<!DOCTYPE html>')
            // Stub references the per-app bundle on whichever origin
            // MCP_APPS_BASE_URL points at — the harness sets it to its own origin.
            expect(text).toMatch(/\/ui-apps\/debug\/main\.js/)
        })

        it('serves the UI app static asset over HTTP', async () => {
            // The asset URL is `${MCP_APPS_BASE_URL}/ui-apps/<app>/main.js`.
            // Hono uses @hono/node-server's serveStatic; CF uses the Workers
            // Static Assets binding configured in wrangler.jsonc.
            const assetUrl = new URL('/ui-apps/debug/main.js', harness.baseUrl)
            const response = await harness.fetch(assetUrl)
            expect(response.status).toBe(200)
            const ctype = response.headers.get('content-type') || ''
            expect(ctype).toMatch(/javascript|ecmascript/)
            const body = await response.text()
            expect(body.length).toBeGreaterThan(0)
        })
    })
}

// Transport-level resilience that the higher-level SDK suites don't reach:
//   - the legacy `/sse → /mcp` 308 redirect (deprecation contract)
//   - the 404-on-unknown-session-id contract that clients lean on to recover
//     after a pod is gone (graceful-shutdown story; spec-required behavior)
export function defineResilienceTests(
    label: string,
    getHarness: () => Promise<ProtocolTestHarness> | ProtocolTestHarness
): void {
    describe(`MCP transport resilience (${label})`, () => {
        // /sse is deprecated; clients still pointed at the legacy URL must land
        // on /mcp with the `_deprecated=sse` marker so analytics can correlate.
        // The redirect is `manual` because some fetch implementations follow
        // 308s automatically and we want to assert on the response itself.
        it('redirects /sse to /mcp with the _deprecated=sse marker', async () => {
            const harness = await getHarness()
            const sseUrl = new URL('/sse', harness.baseUrl)
            const response = await harness.fetch(sseUrl, { redirect: 'manual' })
            expect(response.status).toBe(308)
            const location = response.headers.get('location')
            expect(location).toBeTruthy()
            const target = new URL(location!)
            expect(target.pathname).toBe('/mcp')
            expect(target.searchParams.get('_deprecated')).toBe('sse')
        })

        it('redirects /sse subpaths to /mcp subpaths', async () => {
            const harness = await getHarness()
            const sseSubpath = new URL('/sse/message', harness.baseUrl)
            const response = await harness.fetch(sseSubpath, { redirect: 'manual' })
            expect(response.status).toBe(308)
            const target = new URL(response.headers.get('location')!)
            expect(target.pathname).toBe('/mcp/message')
            expect(target.searchParams.get('_deprecated')).toBe('sse')
        })

        // Stateful runtimes (CF Durable Objects) reject unknown session IDs with
        // a 4xx so the client re-runs `initialize`. Stateless runtimes (Hono) ignore
        // the header and process the request normally — there are no sessions to validate.
        it('rejects requests with an unknown Mcp-Session-Id so the client re-inits', async () => {
            const harness = await getHarness()
            if (harness.stateless) {
                const mcpUrl = new URL('/mcp', harness.baseUrl)
                const response = await harness.fetch(mcpUrl, {
                    method: 'POST',
                    redirect: 'manual',
                    headers: {
                        Authorization: `Bearer ${harness.token}`,
                        'Content-Type': 'application/json',
                        Accept: 'application/json, text/event-stream',
                        'Mcp-Session-Id': 'session-that-does-not-exist',
                    },
                    body: JSON.stringify({
                        jsonrpc: '2.0',
                        id: 'recovery-probe',
                        method: 'tools/list',
                        params: {},
                    }),
                })
                expect(response.status).toBeLessThan(500)
                return
            }

            const mcpUrl = new URL('/mcp', harness.baseUrl)
            const response = await harness.fetch(mcpUrl, {
                method: 'POST',
                redirect: 'manual',
                headers: {
                    Authorization: `Bearer ${harness.token}`,
                    'Content-Type': 'application/json',
                    Accept: 'application/json, text/event-stream',
                    'Mcp-Session-Id': 'session-that-does-not-exist',
                },
                body: JSON.stringify({
                    jsonrpc: '2.0',
                    id: 'recovery-probe',
                    method: 'tools/list',
                    params: {},
                }),
            })
            expect(response.status).toBeGreaterThanOrEqual(400)
            expect(response.status).toBeLessThan(500)
        })
    })
}

// Session ID tracking: the server mints an `Mcp-Session-Id` on initialize and
// echoes it on every response. Clients echo it back so the server can correlate
// requests to a logical session for analytics and cache scoping.
//
// These tests use the real MCP SDK client to verify the session ID flows through
// the full transport lifecycle — the SDK's StreamableHTTPClientTransport
// automatically captures the header from the init response and echoes it on
// every subsequent request.
export function defineSessionTrackingTests(
    label: string,
    getHarness: () => Promise<ProtocolTestHarness> | ProtocolTestHarness
): void {
    describe(`MCP session tracking (${label})`, () => {
        let client: Client
        let transport: StreamableHTTPClientTransport

        afterEach(async () => {
            await safeClose(client)
        })

        async function connectClient(
            harness: ProtocolTestHarness,
            extraHeaders: Record<string, string> = {}
        ): Promise<void> {
            transport = new StreamableHTTPClientTransport(new URL('/mcp', harness.baseUrl), {
                fetch: harness.fetch,
                requestInit: {
                    headers: {
                        Authorization: `Bearer ${harness.token}`,
                        ...extraHeaders,
                    },
                },
            })
            client = new Client({ name: 'session-tracking-test', version: '0.0.1' }, { capabilities: {} })
            await client.connect(transport as ConnectableTransport)
        }

        it('SDK transport captures a UUID session ID after init', async () => {
            const harness = await getHarness()
            await connectClient(harness)

            expect(transport.sessionId).toBeTruthy()
            expect(transport.sessionId).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/)
        })

        it('session ID persists through tools/list after init', async () => {
            const harness = await getHarness()
            await connectClient(harness)
            const sessionId = transport.sessionId

            const { tools } = await client.listTools()
            expect(tools.length).toBeGreaterThan(0)
            expect(transport.sessionId).toBe(sessionId)
        })

        it('session ID persists through a tool call', async () => {
            const harness = await getHarness()
            await connectClient(harness)
            const sessionId = transport.sessionId

            await client.callTool({ name: 'organization-get', arguments: {} })
            expect(transport.sessionId).toBe(sessionId)
        })

        it('session ID persists through multiple sequential tool calls', async () => {
            const harness = await getHarness()
            await connectClient(harness)
            const sessionId = transport.sessionId

            await client.listTools()
            await client.callTool({ name: 'organization-get', arguments: {} })
            await client.listResources()
            expect(transport.sessionId).toBe(sessionId)
        })

        it('exec mode gets a session ID that persists through calls', async () => {
            const harness = await getHarness()
            await connectClient(harness, { 'x-posthog-mcp-mode': 'cli' })
            const sessionId = transport.sessionId

            expect(sessionId).toBeTruthy()
            await client.callTool({ name: 'exec', arguments: { command: 'tools' } })
            expect(transport.sessionId).toBe(sessionId)
        })

        it('two independent clients get different session IDs', async () => {
            const harness = await getHarness()

            await connectClient(harness)
            const sessionId1 = transport.sessionId
            await safeClose(client)

            await connectClient(harness)
            const sessionId2 = transport.sessionId

            expect(sessionId1).toBeTruthy()
            expect(sessionId2).toBeTruthy()
            expect(sessionId1).not.toBe(sessionId2)
        })
    })
}

// Raw JSON-RPC dispatcher behavior that bypasses the SDK client. The SDK
// normalizes / hides a lot of the wire format, so we drop down to fetch() to
// assert on the contract MCP clients in the wild actually depend on:
//   - parse errors return JSON-RPC `error` payloads (code -32700) at HTTP 200
//   - notifications (no `id`) return 202 No Content
//   - `ping` returns an empty result
//   - batch requests return an array, single request returns an object
//   - body / batch size limits are enforced before reaching tool dispatch
//   - unknown methods return `MethodNotFound` (-32601) rather than 500
//
// Each test sends a complete JSON-RPC envelope so a regression in the
// dispatcher (e.g. dropping the `id` echo, changing the error code, returning
// 500 instead of 200) shows up here rather than as a vague client-side timeout.
export function defineJsonRpcEdgeCaseTests(
    label: string,
    getHarness: () => Promise<ProtocolTestHarness> | ProtocolTestHarness
): void {
    describe(`MCP JSON-RPC edge cases (${label})`, () => {
        async function postMcp(
            harness: ProtocolTestHarness,
            body: string | Uint8Array,
            extraHeaders: Record<string, string> = {}
        ): Promise<Response> {
            return harness.fetch(new URL('/mcp', harness.baseUrl), {
                method: 'POST',
                headers: {
                    Authorization: `Bearer ${harness.token}`,
                    'Content-Type': 'application/json',
                    Accept: 'application/json, text/event-stream',
                    ...extraHeaders,
                },
                // Cast to BodyInit because Node's `fetch` accepts both string and Uint8Array.
                body: body as unknown as BodyInit,
            })
        }

        it('returns a JSON-RPC parse error for a malformed body', async () => {
            const harness = await getHarness()
            const res = await postMcp(harness, '{not-json')
            expect(res.status).toBe(200)
            const json = (await res.json()) as {
                jsonrpc?: string
                error?: { code?: number; message?: string }
            }
            expect(json.jsonrpc).toBe('2.0')
            expect(json.error?.code).toBe(-32700)
        })

        it('returns a JSON-RPC parse error for an empty body', async () => {
            const harness = await getHarness()
            const res = await postMcp(harness, '')
            expect(res.status).toBe(200)
            const json = (await res.json()) as { error?: { code?: number } }
            expect(json.error?.code).toBe(-32700)
        })

        // A notification has no `id`. Per the JSON-RPC spec the server must not
        // respond with a result envelope — the dispatcher returns 202 No Content
        // (matches MCP streamable-http behavior). A regression that started
        // sending a JSON body back would make some clients (notably the SDK
        // transport) raise on the unexpected response.
        it('returns 202 with no body for a JSON-RPC notification', async () => {
            const harness = await getHarness()
            const res = await postMcp(
                harness,
                JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized', params: {} })
            )
            expect(res.status).toBe(202)
            const text = await res.text()
            expect(text).toBe('')
        })

        it('responds to ping with an empty result', async () => {
            const harness = await getHarness()
            const res = await postMcp(harness, JSON.stringify({ jsonrpc: '2.0', id: 'ping-1', method: 'ping' }))
            expect(res.status).toBe(200)
            const json = (await res.json()) as { id?: string; result?: Record<string, unknown> }
            expect(json.id).toBe('ping-1')
            expect(json.result).toBeTruthy()
            expect(json.result).toEqual({})
        })

        it('returns MethodNotFound for an unknown method', async () => {
            const harness = await getHarness()
            const res = await postMcp(harness, JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'no/such/method' }))
            expect(res.status).toBe(200)
            const json = (await res.json()) as { error?: { code?: number; message?: string } }
            expect(json.error?.code).toBe(-32601)
        })

        // Batch requests are a JSON-RPC feature MCP clients use to bundle
        // initialize + tools/list (saves a round-trip on cold start). The
        // dispatcher must return an array when given an array, regardless of
        // batch size — including the degenerate single-element array.
        it('returns an array response for a batch with one request', async () => {
            const harness = await getHarness()
            const res = await postMcp(harness, JSON.stringify([{ jsonrpc: '2.0', id: 'batch-1', method: 'ping' }]))
            expect(res.status).toBe(200)
            const json = (await res.json()) as unknown
            expect(Array.isArray(json)).toBe(true)
            expect((json as unknown[]).length).toBe(1)
        })

        it('returns each request id in a multi-request batch', async () => {
            const harness = await getHarness()
            const res = await postMcp(
                harness,
                JSON.stringify([
                    { jsonrpc: '2.0', id: 'a', method: 'ping' },
                    { jsonrpc: '2.0', id: 'b', method: 'ping' },
                    { jsonrpc: '2.0', id: 'c', method: 'ping' },
                ])
            )
            expect(res.status).toBe(200)
            const json = (await res.json()) as Array<{ id: string }>
            expect(json.length).toBe(3)
            expect(json.map((r) => r.id).sort()).toEqual(['a', 'b', 'c'])
        })

        it('returns 202 for a batch composed entirely of notifications', async () => {
            const harness = await getHarness()
            const res = await postMcp(
                harness,
                JSON.stringify([
                    { jsonrpc: '2.0', method: 'notifications/initialized' },
                    { jsonrpc: '2.0', method: 'notifications/initialized' },
                ])
            )
            expect(res.status).toBe(202)
        })

        // The dispatcher caps batches at MAX_BATCH_SIZE (100). Anything bigger
        // returns InvalidRequest — the cap exists so a buggy client can't
        // amplify a single connection into 10k Promise dispatches.
        it('rejects an oversized batch with InvalidRequest', async () => {
            const harness = await getHarness()
            const messages = Array.from({ length: 101 }, (_, i) => ({
                jsonrpc: '2.0',
                id: i,
                method: 'ping',
            }))
            const res = await postMcp(harness, JSON.stringify(messages))
            expect(res.status).toBe(200)
            const json = (await res.json()) as { error?: { code?: number } }
            expect(json.error?.code).toBe(-32600)
        })

        // The body limit (MAX_BODY_BYTES = 1 MiB) is enforced based on
        // Content-Length. We send an actual oversized body so undici accepts
        // the request, and pass Content-Length explicitly so transports that
        // don't auto-set it (Hono's in-process `app.request`) still hit the
        // dispatcher's size guard.
        it('rejects a body larger than the size cap', async () => {
            const harness = await getHarness()
            const padding = 'a'.repeat(1_572_864) // 1.5 MiB
            const oversizedBody = JSON.stringify({
                jsonrpc: '2.0',
                id: 1,
                method: 'ping',
                params: { padding },
            })
            const res = await postMcp(harness, oversizedBody, {
                'Content-Length': String(oversizedBody.length),
            })
            expect(res.status).toBe(200)
            const json = (await res.json()) as { error?: { code?: number } }
            expect(json.error?.code).toBe(-32600)
        })
    })
}

// Public HTTP routes (everything that isn't /mcp). These are how kube probes,
// load balancers, OAuth clients, and OpenAI's MCP marketplace verifier discover
// and validate the server. They have to work even if /mcp is broken, so they
// get their own test group.
//
// Cases:
//   - /, /health, /healthz, /readyz, /metrics — kubelet + monitoring
//   - /.well-known/openai-apps-challenge — OpenAI marketplace identity proof
//   - /.well-known/oauth-protected-resource{,/mcp} — RFC 9728 metadata that
//     clients use to discover the authorization server
//   - /sse → /mcp 308 (also covered in resilience tests, asserted here against
//     the real listener so we know the redirect is wired in the routing chain)
//   - GET / PUT / DELETE on /mcp → 405 (only POST is supported)
//   - 404 for unknown paths
//   - Security headers on every response
//
// This suite assumes the harness has `publicRoutes: true` (the Hono runtime
// does — the CF runtime serves public routes via the Workers Static Assets
// binding which has different semantics, so it gets its own suite).
export function defineHttpRouteTests(
    label: string,
    getHarness: () => Promise<ProtocolTestHarness> | ProtocolTestHarness
): void {
    describe(`MCP HTTP routes (${label})`, () => {
        it('redirects GET / to the docs', async () => {
            const harness = await getHarness()
            const res = await harness.fetch(new URL('/', harness.baseUrl), { redirect: 'manual' })
            expect([301, 302, 307, 308]).toContain(res.status)
            expect(res.headers.get('location')).toContain('posthog.com')
        })

        it.each(['/health', '/healthz'])('returns 200 ok on %s', async (path) => {
            const harness = await getHarness()
            const res = await harness.fetch(new URL(path, harness.baseUrl))
            expect(res.status).toBe(200)
            const json = (await res.json()) as { status?: string }
            expect(json.status).toBe('ok')
        })

        // /readyz piggy-backs on Redis health. With Redis up we expect 200;
        // with Redis down we expect a 5xx. The harness boots a healthy
        // Redis, so we assert success here — a regression that started
        // ignoring the Redis ping would surface as the wrong status code.
        it('returns 200 on /readyz when the stack is healthy', async () => {
            const harness = await getHarness()
            const res = await harness.fetch(new URL('/readyz', harness.baseUrl))
            expect(res.status).toBe(200)
            const json = (await res.json()) as { status?: string; redis?: string }
            expect(json.status).toBe('ok')
            expect(json.redis).toBe('healthy')
        })

        it('serves Prometheus metrics on /metrics', async () => {
            const harness = await getHarness()
            const res = await harness.fetch(new URL('/metrics', harness.baseUrl))
            expect(res.status).toBe(200)
            const ctype = res.headers.get('content-type') || ''
            expect(ctype).toContain('text/plain')
            const body = await res.text()
            // Prom client always emits a process_* family — assert on it so we
            // know the registry was actually rendered.
            expect(body).toMatch(/# HELP\s/)
            expect(body).toMatch(/# TYPE\s/)
        })

        it('returns the openai apps challenge token', async () => {
            const harness = await getHarness()
            const res = await harness.fetch(new URL('/.well-known/openai-apps-challenge', harness.baseUrl))
            expect(res.status).toBe(200)
            const body = await res.text()
            // The challenge token is a fixed value — if a refactor accidentally
            // changes it, OpenAI's marketplace listing will silently break.
            expect(body).toBe('pRLV9JYbPOF5Dy039v3Rn3-qrMuKqZ2_4SsX9GoL9aU')
        })

        it('returns RFC 9728 OAuth protected resource metadata', async () => {
            const harness = await getHarness()
            const res = await harness.fetch(new URL('/.well-known/oauth-protected-resource/mcp', harness.baseUrl))
            expect(res.status).toBe(200)
            const json = (await res.json()) as {
                resource?: string
                authorization_servers?: string[]
                scopes_supported?: string[]
                bearer_methods_supported?: string[]
            }
            expect(json.resource).toMatch(/\/mcp$/)
            expect(Array.isArray(json.authorization_servers)).toBe(true)
            expect((json.authorization_servers ?? []).length).toBeGreaterThan(0)
            expect(json.bearer_methods_supported).toEqual(['header'])
            expect(Array.isArray(json.scopes_supported)).toBe(true)
            expect((json.scopes_supported ?? []).length).toBeGreaterThan(0)
            // The metadata is meant to be cached aggressively — verify the
            // Cache-Control header is set so reverse proxies treat it right.
            expect(res.headers.get('cache-control') || '').toMatch(/max-age=\d+/)
        })

        it('redirects /.well-known/oauth-authorization-server to the authorization server', async () => {
            const harness = await getHarness()
            const res = await harness.fetch(new URL('/.well-known/oauth-authorization-server', harness.baseUrl), {
                redirect: 'manual',
            })
            expect([301, 302]).toContain(res.status)
            // The destination origin varies by environment (prod uses
            // `oauth.posthog.com`, CI runs a local auth server at
            // `localhost:8000`). Just check the redirect is to a different
            // origin than the MCP server itself — that's the contract.
            const location = res.headers.get('location') || ''
            expect(location).toBeTruthy()
            const target = new URL(location)
            expect(target.origin).not.toBe(harness.baseUrl.origin)
        })

        // /register and /token are MCP-spec fallback endpoints. They have to
        // 307 (not 302) so the client preserves the POST + body across the hop
        // — anything else loses the registration / token-exchange payload.
        it.each(['/register', '/token'])('redirects POST %s with 307 to preserve the request body', async (path) => {
            const harness = await getHarness()
            const res = await harness.fetch(new URL(path, harness.baseUrl), {
                method: 'POST',
                redirect: 'manual',
            })
            expect(res.status).toBe(307)
            expect(res.headers.get('location') || '').toContain('/oauth/')
        })

        it.each(['GET', 'PUT', 'DELETE', 'PATCH'])(
            'rejects %s on /mcp with 405 (POST-only endpoint)',
            async (method) => {
                const harness = await getHarness()
                const res = await harness.fetch(new URL('/mcp', harness.baseUrl), {
                    method,
                    headers: { Authorization: `Bearer ${harness.token}` },
                })
                expect(res.status).toBe(405)
            }
        )

        it('returns 404 for unknown paths', async () => {
            const harness = await getHarness()
            const res = await harness.fetch(new URL('/this-path-does-not-exist', harness.baseUrl))
            expect(res.status).toBe(404)
        })

        // Defense-in-depth security headers must be on every response, not just
        // /mcp. Reverse proxies can override these, but the server should set
        // sensible defaults so a misconfigured proxy doesn't expose us.
        it('sets X-Content-Type-Options and X-Frame-Options on responses', async () => {
            const harness = await getHarness()
            const res = await harness.fetch(new URL('/healthz', harness.baseUrl))
            expect(res.headers.get('X-Content-Type-Options')).toBe('nosniff')
            expect(res.headers.get('X-Frame-Options')).toBe('DENY')
        })
    })
}

// Authentication enforcement at the /mcp boundary. The streamable handler is
// the only path that accepts unauthenticated public traffic, so all rejection
// paths run through one chokepoint. These tests use raw fetch so we can poke
// at the WWW-Authenticate header (which the SDK strips off).
export function defineAuthTests(
    label: string,
    getHarness: () => Promise<ProtocolTestHarness> | ProtocolTestHarness
): void {
    describe(`MCP auth (${label})`, () => {
        async function postUnauthed(
            harness: ProtocolTestHarness,
            headers: Record<string, string> = {}
        ): Promise<Response> {
            return harness.fetch(new URL('/mcp', harness.baseUrl), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    Accept: 'application/json, text/event-stream',
                    ...headers,
                },
                body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'ping' }),
            })
        }

        it('returns 401 with WWW-Authenticate when the Authorization header is missing', async () => {
            const harness = await getHarness()
            const res = await postUnauthed(harness)
            expect(res.status).toBe(401)
            const wwwAuth = res.headers.get('WWW-Authenticate') || ''
            expect(wwwAuth.toLowerCase()).toContain('bearer')
            // The challenge points clients at the protected-resource metadata
            // — that's how RFC 9728 discovery bootstraps from a 401.
            expect(wwwAuth).toContain('oauth-protected-resource')
        })

        it('returns 401 for a bearer with no token value', async () => {
            const harness = await getHarness()
            const res = await postUnauthed(harness, { Authorization: 'Bearer' })
            expect(res.status).toBe(401)
        })

        it('returns 401 for a token that does not look like a PostHog API key', async () => {
            const harness = await getHarness()
            const res = await postUnauthed(harness, { Authorization: 'Bearer not_a_phx_or_pha_token' })
            expect(res.status).toBe(401)
            const body = await res.text()
            // The format-check rejection has a distinctive body so a regression
            // that started letting bad-prefix tokens through to PostHog would
            // surface here as a different status / body.
            expect(body.toLowerCase()).toContain('invalid token')
        })

        it('returns 401 for a non-Bearer auth scheme', async () => {
            const harness = await getHarness()
            const res = await postUnauthed(harness, { Authorization: 'Basic dXNlcjpwYXNz' })
            expect(res.status).toBe(401)
        })

        // (The valid-token success path is implicitly covered by every test in
        // `defineMcpProtocolTests` — every SDK client.connect() call exercises
        // it. We deliberately don't repeat it here with raw fetch because the
        // CF Workers runtime returns SSE bodies instead of plain JSON, so a
        // single raw-fetch assertion wouldn't work across both runtimes.)
    })
}

// Tool behavior against the real PostHog API. These tests assert on the actual
// response shape rather than just "the call didn't error" — that way a
// regression in the API client (wrong path, dropped query param) shows up here
// instead of as a vague "the agent gave a weird answer" bug report.
//
// All tests in this group skip if the harness wasn't given orgId / projectId.
export function defineToolBehaviorTests(
    label: string,
    getHarness: () => Promise<ProtocolTestHarness> | ProtocolTestHarness
): void {
    describe(`MCP tool behavior (${label})`, () => {
        let client: Client
        let harness: ProtocolTestHarness

        beforeEach(async () => {
            harness = await getHarness()
            const built = buildStreamableClient(harness)
            client = built.client
            await client.connect(built.transport as ConnectableTransport)
        })

        afterEach(async () => {
            await safeClose(client)
        })

        function decodeText(content: unknown): string {
            if (!Array.isArray(content) || content.length === 0) {
                return ''
            }
            return content
                .map((block) => {
                    if (block && typeof block === 'object' && 'text' in block) {
                        return String((block as { text: unknown }).text ?? '')
                    }
                    return ''
                })
                .join('\n')
        }

        it('projects-get returns the test project among the results', async ({ skip }) => {
            if (!harness.projectId) {
                skip('Set TEST_PROJECT_ID to run the projects-get behavior test.')
                return
            }
            const result = await client.callTool({ name: 'projects-get', arguments: {} })
            if (result.isError) {
                throw new Error(`projects-get errored: ${decodeText(result.content)}`)
            }
            const text = decodeText(result.content)
            // The tool serializes the project list as text; assert the test
            // project's id is referenced so we know the upstream call really
            // talked to the configured org.
            expect(text).toContain(harness.projectId)
        })

        it('switch-project succeeds for the configured project id', async ({ skip }) => {
            if (!harness.projectId) {
                skip('Set TEST_PROJECT_ID to run the switch-project behavior test.')
                return
            }
            const result = await client.callTool({
                name: 'switch-project',
                arguments: { projectId: Number(harness.projectId) },
            })
            expect(result.isError).toBeFalsy()
            const text = decodeText(result.content)
            expect(text.toLowerCase()).toContain('switched')
            expect(text).toContain(String(harness.projectId))
        })

        // After context switch the tool catalog should remain stable — a
        // regression that re-ran the dispatcher's warmup on every call would
        // surface as a missing tool here.
        it('tools/list returns the same set before and after a switch-project call', async ({ skip }) => {
            if (!harness.projectId) {
                skip('Set TEST_PROJECT_ID to run the catalog-stability test.')
                return
            }
            const before = await client.listTools()
            await client.callTool({
                name: 'switch-project',
                arguments: { projectId: Number(harness.projectId) },
            })
            const after = await client.listTools()
            const beforeNames = new Set(before.tools.map((t) => t.name))
            const afterNames = new Set(after.tools.map((t) => t.name))
            expect(afterNames).toEqual(beforeNames)
        })

        // Tool-input validation lives in the executor (zod safeParse). A
        // validation failure has to come back as an in-band `isError: true`
        // result, NOT a JSON-RPC error — otherwise SDK clients would tear down
        // the session.
        it('returns an isError payload for invalid tool arguments', async () => {
            const result = await client.callTool({
                name: 'switch-project',
                arguments: { projectId: 'not-a-number' as unknown as number },
            })
            expect(result.isError).toBe(true)
            const text = decodeText(result.content)
            expect(text.toLowerCase()).toContain('invalid')
        })

        it('switch-project does a soft switch: a non-existent project id still resolves', async () => {
            // switch-project writes the requested id to the cache before
            // calling PostHog to fetch project metadata. When the project
            // doesn't exist the metadata fetch fails, but the cache write
            // has already landed — so the tool returns success and the
            // content references the requested id. This is the documented
            // soft-switch contract: agents pinning to an id they don't
            // strictly own won't get a hard error.
            const result = await client.callTool({
                name: 'switch-project',
                arguments: { projectId: 999_999_999 },
            })
            expect(result.isError).toBeFalsy()
            const text = decodeText(result.content)
            expect(text).toContain('999999999')
        })

        // organization-get is the canonical "is the upstream reachable" probe.
        // We hit it through the MCP layer and assert the org id we read back
        // matches the configured one — that exercises the full chain: SDK
        // client → streamable transport → dispatcher → tool executor → API
        // client → PostHog.
        it('organization-get returns the configured org id', async ({ skip }) => {
            if (!harness.orgId) {
                skip('Set TEST_ORG_ID to run the organization-get behavior test.')
                return
            }
            const result = await client.callTool({ name: 'organization-get', arguments: {} })
            if (result.isError) {
                throw new Error(`organization-get errored: ${decodeText(result.content)}`)
            }
            const text = decodeText(result.content)
            expect(text).toContain(harness.orgId)
        })

        // Multi-step flow: switch-project sets the active project in the
        // per-user cache, and a subsequent project-scoped tool reads from
        // that cache. If the cache write doesn't land before the next
        // request resolves state (e.g. a Redis write that didn't await),
        // the second call would either error out with "missing project
        // context" or read from a stale project.
        //
        // We assert the second call succeeds without error — that's enough
        // to know the active-project context flowed across the two
        // requests on the same MCP session.
        it('switch-project then a project-scoped tool call resolves the active project', async ({ skip }) => {
            if (!harness.projectId) {
                skip('Set TEST_PROJECT_ID to run the multi-step context test.')
                return
            }
            const switchResult = await client.callTool({
                name: 'switch-project',
                arguments: { projectId: Number(harness.projectId) },
            })
            expect(switchResult.isError).toBeFalsy()
            // feature-flag-get-all needs an active project context. It
            // doesn't take a projectId argument — it reads from the cache
            // populated by switch-project.
            const listResult = await client.callTool({
                name: 'feature-flag-get-all',
                arguments: {},
            })
            if (listResult.isError) {
                throw new Error(`feature-flag-get-all errored after switch-project: ${decodeText(listResult.content)}`)
            }
        })

        // Multiple sequential calls on the same session should each see a
        // fresh per-request context but the same cached active project.
        // A regression that started rebuilding the API client per call
        // (dropping the cached org/project) would surface as either
        // missing-context errors or differing org ids across calls.
        it('reads the same active context across multiple sequential calls', async ({ skip }) => {
            if (!harness.orgId) {
                skip('Set TEST_ORG_ID to run the sequential-context test.')
                return
            }
            const a = await client.callTool({ name: 'organization-get', arguments: {} })
            const b = await client.callTool({ name: 'organization-get', arguments: {} })
            expect(a.isError).toBeFalsy()
            expect(b.isError).toBeFalsy()
            expect(decodeText(a.content)).toContain(harness.orgId)
            expect(decodeText(b.content)).toContain(harness.orgId)
        })

        // Concurrent tool calls on the same session must not interfere with
        // each other. The SDK transport multiplexes them over one HTTP
        // connection; the dispatcher must keep their per-call state
        // independent (no shared mutable buffers, no cross-talk between
        // tool args).
        it('handles concurrent tool calls on the same session without cross-talk', async ({ skip }) => {
            if (!harness.orgId || !harness.projectId) {
                skip('Set TEST_ORG_ID and TEST_PROJECT_ID to run the concurrent-call test.')
                return
            }
            const [orgRes, projectsRes] = await Promise.all([
                client.callTool({ name: 'organization-get', arguments: {} }),
                client.callTool({ name: 'projects-get', arguments: {} }),
            ])
            expect(orgRes.isError).toBeFalsy()
            expect(projectsRes.isError).toBeFalsy()
            expect(decodeText(orgRes.content)).toContain(harness.orgId)
            expect(decodeText(projectsRes.content)).toContain(harness.projectId)
        })

        // A tool error (validation or upstream 4xx) must come back as an
        // in-band `isError: true` result. The session must remain usable
        // for the next call — otherwise an agent that hits one bad arg
        // would lose its whole session.
        it('recovers cleanly: a valid tool call works after an isError result', async ({ skip }) => {
            if (!harness.orgId) {
                skip('Set TEST_ORG_ID to run the error-recovery test.')
                return
            }
            const bad = await client.callTool({
                name: 'switch-project',
                arguments: { projectId: 'definitely-not-a-number' as unknown as number },
            })
            expect(bad.isError).toBe(true)
            const good = await client.callTool({ name: 'organization-get', arguments: {} })
            expect(good.isError).toBeFalsy()
            expect(decodeText(good.content)).toContain(harness.orgId)
        })

        // Tools wrapped with `withUiApp(...)` ship a `structuredContent`
        // payload on per-call results. The MCP client uses that
        // structured payload (alongside the tool-definition's
        // `_meta.ui.resourceUri`) to render the UI app for the call.
        //
        // The UI metadata itself only flows back through `_meta` in
        // single-exec mode (see `buildToolResultPayload`'s
        // `includeUiResponseMeta` flag) — so for the default tool-call
        // path the assertion that matters is "structuredContent is
        // populated".
        it('returns structuredContent on a UI-app tool call', async () => {
            const { tools } = await client.listTools()
            const debugTool = tools.find((t) => t.name === 'debug-mcp-ui-apps')
            if (!debugTool) {
                throw new Error('debug-mcp-ui-apps tool is missing — expected it for the UI-app per-call probe')
            }
            // Sanity check that the tool definition still has the UI
            // metadata wired (otherwise structuredContent wouldn't be
            // populated even with a working pipeline).
            const meta = (debugTool as { _meta?: { ui?: { resourceUri?: string } } })._meta
            expect(meta?.ui?.resourceUri).toBeTruthy()

            const result = await client.callTool({ name: 'debug-mcp-ui-apps', arguments: {} })
            if (result.isError) {
                throw new Error(`debug-mcp-ui-apps errored: ${decodeText(result.content)}`)
            }
            const structured = (result as { structuredContent?: Record<string, unknown> }).structuredContent
            expect(structured).toBeTruthy()
            // The debug handler emits `message` and `sdkInfo` — check at
            // least one survives the pipeline so we know the payload
            // wasn't replaced with an empty object.
            expect(structured?.message).toBeTruthy()
        })

        // switch-organization is symmetric with switch-project — same cache-
        // write pattern, same expected flow. Worth its own test because the
        // two go through different code paths (different cache keys, different
        // upstream endpoints) and could regress independently.
        it('switch-organization succeeds for the configured org id', async ({ skip }) => {
            if (!harness.orgId) {
                skip('Set TEST_ORG_ID to run the switch-organization behavior test.')
                return
            }
            const result = await client.callTool({
                name: 'switch-organization',
                arguments: { orgId: harness.orgId },
            })
            expect(result.isError).toBeFalsy()
            const text = decodeText(result.content)
            expect(text.toLowerCase()).toContain('switched')
            expect(text).toContain(harness.orgId)
        })

        it('organization-get reflects a fresh switch-organization', async ({ skip }) => {
            if (!harness.orgId) {
                skip('Set TEST_ORG_ID to run the org-context multi-step test.')
                return
            }
            const switchResult = await client.callTool({
                name: 'switch-organization',
                arguments: { orgId: harness.orgId },
            })
            expect(switchResult.isError).toBeFalsy()
            const orgResult = await client.callTool({ name: 'organization-get', arguments: {} })
            expect(orgResult.isError).toBeFalsy()
            expect(decodeText(orgResult.content)).toContain(harness.orgId)
        })

        // ?projectId=N in the URL pins the active project for the whole
        // session — agents pass this to avoid needing a switch-project
        // tool call first. The state resolver writes it to the cache on
        // every request, so a project-scoped tool should resolve it
        // without an explicit switch.
        it('reads the active project pinned via ?projectId= URL param', async ({ skip }) => {
            if (!harness.projectId) {
                skip('Set TEST_PROJECT_ID to run the pinned-project URL-param test.')
                return
            }
            // Open a fresh client targeted at `/mcp?projectId=<id>` so the
            // pin is set before the first tool call.
            const url = new URL('/mcp', harness.baseUrl)
            url.searchParams.set('projectId', String(harness.projectId))
            const transport = new StreamableHTTPClientTransport(url, {
                fetch: harness.fetch,
                requestInit: { headers: { Authorization: `Bearer ${harness.token}` } },
            })
            const pinnedClient = new Client({ name: 'pinned-project-test', version: '0.0.0' }, { capabilities: {} })
            try {
                await pinnedClient.connect(transport as ConnectableTransport)
                const result = await pinnedClient.callTool({ name: 'feature-flag-get-all', arguments: {} })
                if (result.isError) {
                    throw new Error(`feature-flag-get-all errored with pinned projectId: ${decodeText(result.content)}`)
                }
            } finally {
                await safeClose(pinnedClient)
            }
        })

        // execute-sql is the heaviest upstream call surface in the MCP server:
        // it crosses the API client, the PostHog `/api/environments/<id>/mcp_tools/execute_sql/`
        // endpoint, and ClickHouse via HogQL. If this works end-to-end, the
        // whole query path is wired up.
        //
        // `SELECT 1 AS one` doesn't depend on any ingested data, so it works
        // against a freshly-booted local stack with no seed data.
        //
        // The tool is gated by `query:read` + `insight:read` scopes — if the
        // test API key doesn't carry them, execute-sql won't be in the
        // catalog and we skip rather than fail (a different test would
        // catch the scope-filter regression).
        it('execute-sql runs a trivial HogQL query against the upstream', async ({ skip }) => {
            if (!harness.projectId) {
                skip('Set TEST_PROJECT_ID to run the execute-sql roundtrip test.')
                return
            }
            const { tools } = await client.listTools()
            if (!tools.some((t) => t.name === 'execute-sql')) {
                skip('execute-sql not in catalog for this token — needs query:read + insight:read scopes.')
                return
            }
            await client.callTool({
                name: 'switch-project',
                arguments: { projectId: Number(harness.projectId) },
            })
            const result = await client.callTool({
                name: 'execute-sql',
                arguments: { query: 'SELECT 1 AS one' },
            })
            if (result.isError) {
                throw new Error(`execute-sql errored: ${decodeText(result.content)}`)
            }
            // The exact serialization is at the upstream's discretion (CSV,
            // markdown, etc.) so we don't pin to a specific format. We just
            // check the query output landed in the response body.
            const text = decodeText(result.content)
            expect(text.length).toBeGreaterThan(0)
        })
    })
}

// Catalog filtering by query-param. The MCP server reads `?features=` and
// `?tools=` from the URL to let agents pin themselves to a narrower set of
// capabilities — this is how the OpenAI marketplace, Cursor, and Claude
// Desktop pre-select a vertical (analytics, flags, etc.) rather than serving
// the whole 392-tool catalog.
//
// A regression that dropped the filter would silently inflate every
// agent's available toolset, which is hard to spot without an integration
// test. We use a single `?features=flags` request and assert that the
// returned `tools/list` is (a) non-empty, and (b) a strict subset of the
// unfiltered list.
export function defineCatalogFilterTests(
    label: string,
    getHarness: () => Promise<ProtocolTestHarness> | ProtocolTestHarness
): void {
    describe(`MCP catalog filtering (${label})`, () => {
        async function listToolsWithQuery(
            harness: ProtocolTestHarness,
            search: string
        ): Promise<{ tools: Array<{ name: string }> }> {
            const url = new URL('/mcp', harness.baseUrl)
            url.search = search
            const transport = new StreamableHTTPClientTransport(url, {
                fetch: harness.fetch,
                requestInit: { headers: { Authorization: `Bearer ${harness.token}` } },
            })
            const client = new Client({ name: 'filter-test', version: '0.0.0' }, { capabilities: {} })
            try {
                await client.connect(transport as ConnectableTransport)
                const result = await client.listTools()
                return result
            } finally {
                await safeClose(client)
            }
        }

        it('returns the full catalog when no filter is set', async () => {
            const harness = await getHarness()
            const { tools } = await listToolsWithQuery(harness, '')
            expect(tools.length).toBeGreaterThan(10)
            // organization-get is part of the platform-features catalog and
            // doesn't get filtered out by any feature flag — it's a stable
            // anchor for "this is the full set".
            expect(tools.map((t) => t.name)).toContain('organization-get')
        })

        it('narrows the catalog when ?features= is set', async () => {
            const harness = await getHarness()
            const { tools: full } = await listToolsWithQuery(harness, '')
            const { tools: filtered } = await listToolsWithQuery(harness, '?features=flags')
            expect(filtered.length).toBeGreaterThan(0)
            expect(filtered.length).toBeLessThan(full.length)
            // Every filtered tool must also appear in the full list — the
            // filter is a subset operation, never a superset / replacement.
            const fullNames = new Set(full.map((t) => t.name))
            for (const t of filtered) {
                expect(fullNames.has(t.name)).toBe(true)
            }
            // The `flags` feature group must include the flag tools by name.
            expect(filtered.map((t) => t.name)).toContain('feature-flag-get-all')
        })

        it('pins the catalog to specific tools when ?tools= is set', async () => {
            const harness = await getHarness()
            const { tools } = await listToolsWithQuery(harness, '?tools=organization-get,projects-get')
            expect(tools.length).toBeGreaterThan(0)
            const names = tools.map((t) => t.name)
            // Pinned tools must appear; non-pinned ones must not.
            expect(names).toContain('organization-get')
            expect(names).toContain('projects-get')
            expect(names).not.toContain('feature-flag-get-all')
        })

        // An unknown feature yields no tools after filtering. The Hono
        // runtime hands back an empty `tools/list` result; the CF
        // Workers runtime's agents SDK doesn't register the `tools/list`
        // method when there are zero tools to expose, so the same
        // request gets back `Method not found` instead. Both are valid
        // runtime choices — we gate this assertion on the
        // `gracefulUnknown` flag that the Hono harness sets.
        it('returns an empty (but well-formed) list for an unknown feature', async ({ skip }) => {
            const harness = await getHarness()
            if (!harness.gracefulUnknown) {
                skip('Empty-catalog handling is runtime-specific; only the graceful-unknown runtime returns []')
                return
            }
            const { tools } = await listToolsWithQuery(harness, '?features=this-feature-does-not-exist')
            expect(Array.isArray(tools)).toBe(true)
            expect(tools.length).toBe(0)
        })

        // Read-only mode is the safety toggle agents flip when they want
        // to expose the catalog to a read-only chat persona. The filter
        // is at the tool-definition level (`annotations.readOnlyHint`)
        // and any tool without that hint must be dropped. Without this
        // test, a write tool that loses its annotation would still ship
        // to read-only consumers.
        it('drops write tools when ?readonly=true is set', async () => {
            const harness = await getHarness()
            const { tools: full } = await listToolsWithQuery(harness, '')
            const { tools: readonly } = await listToolsWithQuery(harness, '?readonly=true')
            expect(readonly.length).toBeGreaterThan(0)
            expect(readonly.length).toBeLessThan(full.length)
            const readonlyNames = new Set(readonly.map((t) => t.name))
            // The CRUD-y get variants stay; the create / delete / update
            // variants must be gone.
            expect(readonlyNames.has('feature-flag-get-all')).toBe(true)
            expect(readonlyNames.has('create-feature-flag')).toBe(false)
            expect(readonlyNames.has('dashboard-create')).toBe(false)
        })
    })
}

// Initialize-handshake details and session lifecycle. The SDK client hides
// most of the negotiation logic; these tests drop down to raw fetch so we can
// assert on the protocol-version negotiation and capability advertisement.
export function defineSessionLifecycleTests(
    label: string,
    getHarness: () => Promise<ProtocolTestHarness> | ProtocolTestHarness
): void {
    describe(`MCP session lifecycle (${label})`, () => {
        async function initialize(harness: ProtocolTestHarness, protocolVersion?: string): Promise<Response> {
            return harness.fetch(new URL('/mcp', harness.baseUrl), {
                method: 'POST',
                headers: {
                    Authorization: `Bearer ${harness.token}`,
                    'Content-Type': 'application/json',
                    Accept: 'application/json, text/event-stream',
                },
                body: JSON.stringify({
                    jsonrpc: '2.0',
                    id: 'init-1',
                    method: 'initialize',
                    params: {
                        protocolVersion,
                        capabilities: {},
                        clientInfo: { name: 'lifecycle-test', version: '0.0.1' },
                    },
                }),
            })
        }

        it('advertises tools, resources, and prompts capabilities on initialize', async () => {
            const harness = await getHarness()
            const res = await initialize(harness)
            expect(res.status).toBe(200)
            const json = (await res.json()) as {
                result?: {
                    serverInfo?: { name?: string; version?: string }
                    capabilities?: {
                        tools?: { listChanged?: boolean }
                        resources?: { listChanged?: boolean }
                        prompts?: { listChanged?: boolean }
                    }
                    protocolVersion?: string
                    instructions?: string
                }
            }
            expect(json.result?.serverInfo?.name).toBe('PostHog')
            expect(json.result?.serverInfo?.version).toBeTruthy()
            expect(json.result?.capabilities?.tools).toBeTruthy()
            expect(json.result?.capabilities?.resources).toBeTruthy()
            expect(json.result?.capabilities?.prompts).toBeTruthy()
            expect(json.result?.protocolVersion).toBeTruthy()
        })

        // Clients sometimes pin a protocol version. If we know it, we echo it
        // back; if it's unknown we fall back to the latest supported version.
        // A regression that started rejecting unknown versions would break
        // older SDK clients in the wild.
        it('falls back to the latest protocol version for an unknown request', async () => {
            const harness = await getHarness()
            const res = await initialize(harness, '1999-01-01')
            expect(res.status).toBe(200)
            const json = (await res.json()) as { result?: { protocolVersion?: string } }
            expect(json.result?.protocolVersion).toBeTruthy()
            expect(json.result?.protocolVersion).not.toBe('1999-01-01')
        })

        it('echoes a supported protocol version back unchanged', async () => {
            const harness = await getHarness()
            // The current LATEST_PROTOCOL_VERSION is what the SDK requests by
            // default — read it back from a no-pin initialize and re-use it.
            const probe = await initialize(harness)
            const probeJson = (await probe.json()) as { result?: { protocolVersion?: string } }
            const supported = probeJson.result?.protocolVersion
            expect(supported).toBeTruthy()

            const res = await initialize(harness, supported)
            const json = (await res.json()) as { result?: { protocolVersion?: string } }
            expect(json.result?.protocolVersion).toBe(supported)
        })

        // Reinitialize from the same connection should succeed (some clients
        // re-init after detecting a session was reaped). The dispatcher is
        // stateless on the Hono runtime so this is a no-op contract: it must
        // not 4xx, and must hand back fresh capabilities.
        it('handles a repeated initialize on the same connection', async () => {
            const harness = await getHarness()
            const a = await initialize(harness)
            const b = await initialize(harness)
            expect(a.status).toBe(200)
            expect(b.status).toBe(200)
            const aJson = (await a.json()) as { result?: { serverInfo?: { name?: string } } }
            const bJson = (await b.json()) as { result?: { serverInfo?: { name?: string } } }
            expect(aJson.result?.serverInfo?.name).toBe('PostHog')
            expect(bJson.result?.serverInfo?.name).toBe('PostHog')
        })
    })
}

// Resource catalog assertions that go beyond "list isn't empty". The catalog
// has two distinct sources (UI apps + context-mill manifest) and prompts — a
// regression that dropped one source would show up here.
export function defineResourceCatalogTests(
    label: string,
    getHarness: () => Promise<ProtocolTestHarness> | ProtocolTestHarness
): void {
    describe(`MCP resource catalog (${label})`, () => {
        let client: Client
        let harness: ProtocolTestHarness

        beforeEach(async () => {
            harness = await getHarness()
            const built = buildStreamableClient(harness)
            client = built.client
            await client.connect(built.transport as ConnectableTransport)
        })

        afterEach(async () => {
            await safeClose(client)
        })

        it('lists both UI app and context-mill resources', async () => {
            const { resources } = await client.listResources()
            const uris = resources.map((r) => r.uri)
            expect(uris.some((u) => u.startsWith('ui://') || u.startsWith('mcp-ext-app://'))).toBe(true)
            expect(uris.some((u) => u.startsWith('posthog://'))).toBe(true)
        })

        it('every resource entry has a uri, name, and mimeType', async () => {
            const { resources } = await client.listResources()
            expect(resources.length).toBeGreaterThan(0)
            const malformed = resources.filter((r) => !r.uri || !r.name || !r.mimeType)
            expect(malformed).toEqual([])
        })

        // Reading two different resources in sequence — catches a regression
        // where one read mutates shared catalog state and corrupts the next
        // lookup.
        it('reads two distinct resources without cross-contamination', async () => {
            const { resources } = await client.listResources()
            const ui = resources.find((r) => r.uri.startsWith('ui://') || r.uri.startsWith('mcp-ext-app://'))
            const cm = resources.find((r) => r.uri.startsWith('posthog://'))
            if (!ui || !cm) {
                throw new Error('expected at least one ui:// and one posthog:// resource')
            }
            const uiRead = await client.readResource({ uri: ui.uri })
            const cmRead = await client.readResource({ uri: cm.uri })
            expect(uiRead.contents[0]?.uri).toBe(ui.uri)
            expect(cmRead.contents[0]?.uri).toBe(cm.uri)
        })

        // The prompts list may be empty on some manifest revisions (the
        // context-mill manifest doesn't always ship prompts), so this is a
        // shape check rather than a content check — we don't assert
        // length > 0. What we DO require: anything that comes back has
        // a non-empty `name`.
        it('lists prompts as a well-formed array where every entry has a name', async ({ skip }) => {
            if (!harness.gracefulUnknown) {
                skip('Prompts endpoint is wired only on the graceful-unknown runtime.')
                return
            }
            const { prompts } = await client.listPrompts()
            expect(Array.isArray(prompts)).toBe(true)
            const unnamed = prompts.filter((p) => !p.name)
            expect(unnamed).toEqual([])
        })
    })
}

// Single-exec mode: the server exposes one `exec` tool that wraps all inner
// tools. Clients send `x-posthog-mcp-mode: cli` to enter this mode. The exec
// tool accepts a `command` string that dispatches to the inner tool catalog
// via verbs: `tools`, `search <regex>`, `info <tool>`, `call <tool> <json>`.
//
// These tests exercise the full exec flow end-to-end through the dispatcher,
// state resolver, and tool executor — catching regressions in command parsing,
// inner tool dispatch, and result formatting that unit tests on exec.ts alone
// would miss.
export function defineExecModeTests(
    label: string,
    getHarness: () => Promise<ProtocolTestHarness> | ProtocolTestHarness
): void {
    describe(`MCP exec mode (${label})`, () => {
        let client: Client

        beforeEach(async () => {
            const harness = await getHarness()
            const built = buildExecModeClient(harness)
            client = built.client
            await client.connect(built.transport as ConnectableTransport)
        })

        afterEach(async () => {
            await safeClose(client)
        })

        it('lists only the exec tool when in cli mode', async () => {
            const { tools } = await client.listTools()
            expect(tools).toHaveLength(1)
            expect(tools[0]!.name).toBe('exec')
        })

        it('exec "tools" lists available inner tools', async () => {
            const result = await client.callTool({ name: 'exec', arguments: { command: 'tools' } })
            expect(result.isError).toBeFalsy()
            const text = (result.content as Array<{ type: string; text: string }>)[0]?.text ?? ''
            expect(text).toContain('execute-sql')
            expect(text).toContain('organization-get')
        })

        it('exec "search" finds tools by regex', async () => {
            const result = await client.callTool({ name: 'exec', arguments: { command: 'search feature-flag' } })
            expect(result.isError).toBeFalsy()
            const text = (result.content as Array<{ type: string; text: string }>)[0]?.text ?? ''
            expect(text).toContain('feature-flag')
        })

        it('exec "info" returns tool description and schema', async () => {
            const result = await client.callTool({ name: 'exec', arguments: { command: 'info organization-get' } })
            expect(result.isError).toBeFalsy()
            const text = (result.content as Array<{ type: string; text: string }>)[0]?.text ?? ''
            expect(text.length).toBeGreaterThan(50)
            expect(text.toLowerCase()).toContain('organization')
        })

        it('exec "call" dispatches to an inner tool and returns a result', async () => {
            const result = await client.callTool({
                name: 'exec',
                arguments: { command: 'call organization-get {}' },
            })
            expect(result.isError).toBeFalsy()
            const text = (result.content as Array<{ type: string; text: string }>)[0]?.text ?? ''
            expect(text.length).toBeGreaterThan(0)
        })

        it('exec "call" with an unknown tool returns an error message', async () => {
            const result = await client.callTool({
                name: 'exec',
                arguments: { command: 'call nonexistent-tool-xyz {}' },
            })
            const text = (result.content as Array<{ type: string; text: string }>)[0]?.text ?? ''
            expect(text.toLowerCase()).toMatch(/not found|unknown tool/)
        })

        it('exec with an unknown verb returns a helpful error', async () => {
            const result = await client.callTool({
                name: 'exec',
                arguments: { command: 'badverb something' },
            })
            const text = (result.content as Array<{ type: string; text: string }>)[0]?.text ?? ''
            expect(text.toLowerCase()).toMatch(/unknown|unrecognized|invalid/)
        })

        it('exec "call" with invalid JSON returns a parse error', async () => {
            const result = await client.callTool({
                name: 'exec',
                arguments: { command: 'call organization-get {not-json}' },
            })
            const text = (result.content as Array<{ type: string; text: string }>)[0]?.text ?? ''
            expect(text.toLowerCase()).toContain('json')
        })
    })
}
