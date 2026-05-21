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

        beforeEach(async () => {
            const harness = await getHarness()
            const built = buildStreamableClient(harness)
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

        it('returns empty contents for an unknown resource URI', async () => {
            const result = await client.readResource({ uri: 'posthog://does-not-exist' })
            expect(result.contents).toEqual([])
        })

        it('returns empty messages for an unknown prompt name', async () => {
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
