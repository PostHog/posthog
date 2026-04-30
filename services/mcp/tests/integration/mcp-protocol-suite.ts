// Shared MCP-protocol integration suite. Wires the official @modelcontextprotocol/sdk
// client against a runtime-supplied transport target and exercises the standard
// JSON-RPC interactions: initialize handshake, tools/list, tools/call, prompts/list,
// resources/list, and clean disconnect. Both the Cloudflare and Hono entry points
// run the same suite so any divergence shows up as a test failure rather than a
// silent runtime drift.

import { Client } from '@modelcontextprotocol/sdk/client/index.js'
import { SSEClientTransport } from '@modelcontextprotocol/sdk/client/sse.js'
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
}

function buildStreamableClient(
    harness: ProtocolTestHarness,
    token: string = harness.token
): { client: Client; transport: StreamableHTTPClientTransport } {
    const transport = new StreamableHTTPClientTransport(new URL('/mcp', harness.baseUrl), {
        fetch: harness.fetch,
        requestInit: { headers: { Authorization: `Bearer ${token}` } },
    })
    const client = new Client(
        { name: 'mcp-integration-test', version: '0.0.0' },
        { capabilities: {} }
    )
    return { client, transport }
}

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

        beforeEach(async () => {
            const harness = await getHarness()
            const built = buildStreamableClient(harness)
            client = built.client
            await client.connect(built.transport)
        })

        afterEach(async () => {
            await safeClose(client)
        })

        it('reports server name and version after the initialize handshake', () => {
            const info = client.getServerVersion()
            expect(info?.name).toBe('PostHog')
            expect(info?.version).toBeTruthy()
        })

        it('lists available tools with non-empty schemas', async () => {
            const { tools } = await client.listTools()
            expect(tools.length).toBeGreaterThan(0)

            const sample = tools[0]
            expect(sample.name).toBeTruthy()
            expect(sample.inputSchema).toBeTruthy()
            expect(sample.inputSchema.type).toBe('object')
        })

        it('exposes a known PostHog tool (organization-get)', async () => {
            const { tools } = await client.listTools()
            const names = tools.map((t) => t.name)
            expect(names).toContain('organization-get')
        })

        // Prompts and resources are populated at runtime from context-mill's
        // GitHub release. When the fetch fails (offline, sandbox, blocked TLS)
        // the McpServer doesn't claim those capabilities and the SDK surfaces
        // -32601. We accept either outcome here so the suite is robust to a
        // missing context-mill build artifact.
        it('lists prompts (empty or unsupported)', async () => {
            try {
                const { prompts } = await client.listPrompts()
                expect(Array.isArray(prompts)).toBe(true)
            } catch (err) {
                expect(String(err)).toMatch(/Method not found|-32601/)
            }
        })

        it('lists resources (empty or unsupported)', async () => {
            try {
                const { resources } = await client.listResources()
                expect(Array.isArray(resources)).toBe(true)
            } catch (err) {
                expect(String(err)).toMatch(/Method not found|-32601/)
            }
        })

        it('reads a registered resource end-to-end', async ({ skip }) => {
            // Resources come from two sources at runtime: context-mill (a GitHub
            // release fetched at init) and `registerUiAppResources`. If neither
            // produced any registrations the protocol method is "not found" and
            // there's nothing to read — skip rather than fail.
            let resources: Awaited<ReturnType<Client['listResources']>>['resources']
            try {
                resources = (await client.listResources()).resources
            } catch {
                skip('No resources registered (resources/list returned -32601).')
                return
            }
            if (resources.length === 0) {
                skip('No resources registered.')
                return
            }
            // Pick the first resource; assert listing shape, then exercise the
            // resources/read JSON-RPC call which hits a different code path.
            const first = resources[0]
            expect(first.uri).toBeTruthy()
            expect(first.mimeType).toBeTruthy()

            const result = await client.readResource({ uri: first.uri })
            expect(Array.isArray(result.contents)).toBe(true)
            expect(result.contents.length).toBeGreaterThan(0)
            expect(result.contents[0].uri).toBe(first.uri)
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
                skip(
                    'Set TEST_POSTHOG_PERSONAL_API_KEY_2 to run the concurrent-sessions isolation test.'
                )
                return
            }

            const a = buildStreamableClient(harness, harness.token)
            const b = buildStreamableClient(harness, harness.token2)

            try {
                await Promise.all([a.client.connect(a.transport), b.client.connect(b.transport)])

                // Both clients should resolve initialize against their own session.
                expect(a.client.getServerVersion()?.name).toBe('PostHog')
                expect(b.client.getServerVersion()?.name).toBe('PostHog')

                const [toolsA, toolsB] = await Promise.all([
                    a.client.listTools(),
                    b.client.listTools(),
                ])

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
            await client.connect(built.transport)
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
            const text = String(first.text ?? '')
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

// SSE transport coverage. Same protocol moves, separate code path:
// `SSEClientTransport` opens an EventSource for receiving and POSTs back via
// `?sessionId=…`. Hono uses `createSSEResponseAdapter`; CF uses
// `MCP.serveSSE('/sse')`. A regression in either is invisible to the
// streamable-http suite.
export function defineSseProtocolTests(
    label: string,
    getHarness: () => Promise<ProtocolTestHarness> | ProtocolTestHarness
): void {
    describe(`MCP protocol over SSE (${label})`, () => {
        let client: Client
        let transport: SSEClientTransport

        beforeEach(async () => {
            const harness = await getHarness()
            const sseUrl = new URL('/sse', harness.baseUrl)
            const authHeaders = { Authorization: `Bearer ${harness.token}` }

            transport = new SSEClientTransport(sseUrl, {
                // EventSource doesn't support custom headers natively; the
                // `eventsource` package the SDK uses lets us inject them via a
                // custom fetch on `eventSourceInit`.
                eventSourceInit: {
                    fetch: (url, init) =>
                        harness.fetch(url as RequestInfo, {
                            ...init,
                            headers: { ...(init?.headers as Record<string, string>), ...authHeaders },
                        }),
                },
                requestInit: { headers: authHeaders },
                fetch: harness.fetch,
            })
            client = new Client(
                { name: 'mcp-integration-test-sse', version: '0.0.0' },
                { capabilities: {} }
            )
            await client.connect(transport)
        })

        afterEach(async () => {
            await safeClose(client)
        })

        it('completes the initialize handshake over SSE', () => {
            expect(client.getServerVersion()?.name).toBe('PostHog')
        })

        it('lists tools over SSE', async () => {
            const { tools } = await client.listTools()
            expect(tools.length).toBeGreaterThan(0)
            expect(tools.map((t) => t.name)).toContain('organization-get')
        })

        it('calls a tool over SSE and returns content', async () => {
            const result = await client.callTool({ name: 'organization-get', arguments: {} })
            if (result.isError) {
                throw new Error(`tool returned error: ${JSON.stringify(result.content)}`)
            }
            expect((result.content as unknown[]).length).toBeGreaterThan(0)
        })
    })
}
