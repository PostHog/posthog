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
    /** Bearer token forwarded as the `Authorization` header. Must match what the
     * runtime's mocks expect (CF / Hono fixtures both treat any `phx_*` token
     * as authenticated and rely on `oauth/introspect` returning active). */
    token: string
}

export function defineMcpProtocolTests(
    label: string,
    getHarness: () => Promise<ProtocolTestHarness> | ProtocolTestHarness
): void {
    describe(`MCP protocol (${label})`, () => {
        let client: Client
        let transport: StreamableHTTPClientTransport

        beforeEach(async () => {
            const harness = await getHarness()
            const endpoint = new URL('/mcp', harness.baseUrl)

            transport = new StreamableHTTPClientTransport(endpoint, {
                // The SDK's default fetch is `globalThis.fetch`. Override so the
                // CF harness can route through workerd's `SELF.fetch` and the
                // Hono harness can hit its real local listener.
                fetch: harness.fetch,
                requestInit: {
                    headers: { Authorization: `Bearer ${harness.token}` },
                },
            })

            client = new Client(
                { name: 'mcp-integration-test', version: '0.0.0' },
                { capabilities: {} }
            )
            await client.connect(transport)
        })

        afterEach(async () => {
            try {
                await client?.close()
            } catch {
                // SDK Client.close throws if already closed; harmless during teardown.
            }
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
            // Every tool exposes a JSON-Schema input shape; SDK normalizes it to `inputSchema`.
            expect(sample.inputSchema).toBeTruthy()
            expect(sample.inputSchema.type).toBe('object')
        })

        it('exposes a known PostHog tool (organization-get)', async () => {
            const { tools } = await client.listTools()
            const names = tools.map((t) => t.name)
            expect(names).toContain('organization-get')
        })

        // Prompts and resources are populated at runtime from context-mill's
        // GitHub release. In `TEST=1` mode the registration is skipped so the
        // McpServer never claims those capabilities — the SDK then surfaces a
        // -32601 ("Method not found") rather than an empty list. We treat that
        // as a valid outcome so the suite stays usable across both runtimes.
        it('lists prompts (empty or unsupported under TEST=1)', async () => {
            try {
                const { prompts } = await client.listPrompts()
                expect(Array.isArray(prompts)).toBe(true)
            } catch (err) {
                expect(String(err)).toMatch(/Method not found|-32601/)
            }
        })

        it('lists resources (empty or unsupported under TEST=1)', async () => {
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
            expect(result.isError).toBeFalsy()
            expect(Array.isArray(result.content)).toBe(true)
            expect(result.content.length).toBeGreaterThan(0)
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
    })
}
