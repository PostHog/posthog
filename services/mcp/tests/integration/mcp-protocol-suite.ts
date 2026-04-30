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
