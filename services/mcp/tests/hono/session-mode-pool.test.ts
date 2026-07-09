// Verifies the connection-pooling scenario observed in production: Anthropic
// reuses a single `Mcp-Session-Id` across multiple inner clients (Claude
// Code, Claude.ai, Cowork) and differentiates them via the per-request
// `x-anthropic-client` header. The server caches the initial raw session
// identity hints and derives mode from those cached-first hints; a later
// `tools/call` carrying a different vendor must NOT flip the resolved
// mode/version. The same pinning protects a tools-mode session (Cursor) from
// being dragged back to the cli default by a mid-session vendor header.
//
// To probe the resolved mode DIRECTLY we issue a raw `tools/list` on the pooled
// session: cli (single-exec) mode collapses the wire roster to a single `exec`
// tool, while tools mode exposes the full multi-tool roster. That's a direct
// observable for "the resolved mode at headers_2 equals the resolved mode at
// headers_1".
import { Client } from '@modelcontextprotocol/sdk/client/index.js'
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js'
import { setupServer } from 'msw/node'
import { afterAll, beforeAll, describe, expect, it } from 'vitest'

import { createApp } from '@/hono/app'
import type { RedisLike } from '@/hono/cache/RedisCache'

import { contextMillHandler, handlers } from '../workers/fixtures/handlers'
import { makeRedisRateLimitStubs } from './helpers/redis-rate-limit-stubs'

const mswServer = setupServer(...handlers, contextMillHandler)

function createInMemoryRedis(): RedisLike & { ping(): Promise<string> } {
    const store = new Map<string, string>()
    return {
        get: async (key) => store.get(key) ?? null,
        set: async (key, value) => {
            store.set(key, String(value))
            return 'OK'
        },
        del: async (...keys) => {
            let removed = 0
            for (const key of keys) {
                if (store.delete(key)) {
                    removed++
                }
            }
            return removed
        },
        scan: async (cursor) => {
            const cur = String(cursor)
            return [cur === '0' ? 'next' : '0', cur === '0' ? Array.from(store.keys()) : []] as [string, string[]]
        },
        ...makeRedisRateLimitStubs(),
        ping: async () => 'PONG',
    }
}

let app: ReturnType<typeof createApp>['app']
const TOKEN = 'phx_session_mode_pool_test'
const BASE_URL = new URL('http://hono.test')

beforeAll(async () => {
    process.env.TEST = '1'
    process.env.MCP_APPS_BASE_URL = 'https://apps.test'
    mswServer.listen({ onUnhandledRequest: 'bypass' })
    const created = createApp(createInMemoryRedis())
    app = created.app
    await created.warmup()
})

afterAll(() => {
    mswServer.close()
})

const fetchViaApp: typeof fetch = async (input, init) => {
    const url = input instanceof URL ? input : new URL(typeof input === 'string' ? input : input.url)
    return app.request(url.pathname + url.search, init ?? {})
}

type ConnectableTransport = Parameters<Client['connect']>[0]

interface ToolsListResponse {
    result?: { tools?: Array<{ name: string }> }
}

async function listToolsOnSession(sessionId: string, vendorClient: string): Promise<Array<{ name: string }>> {
    const res = await fetchViaApp(new URL('/mcp', BASE_URL), {
        method: 'POST',
        headers: {
            Authorization: `Bearer ${TOKEN}`,
            'Content-Type': 'application/json',
            Accept: 'application/json, text/event-stream',
            'Mcp-Session-Id': sessionId,
            'x-anthropic-client': vendorClient,
        },
        body: JSON.stringify({
            jsonrpc: '2.0',
            id: 'pool-tools-list',
            method: 'tools/list',
            params: {},
        }),
    })
    expect(res.status).toBe(200)
    const json = (await res.json()) as ToolsListResponse
    return json.result?.tools ?? []
}

describe('Resolved mode is preserved across pooled-transport vendor flips', () => {
    it('cli init via x-anthropic-client survives a vendor flip on the same session', async () => {
        // headers_1 — clientInfo.name is the vendor-prefixed pool-owner shape, while
        // the per-request vendor header identifies the inner client as Claude Code.
        // This is the production-pool scenario where the body identifies the
        // transport-owner and the header identifies the live consumer. Neither
        // matches the tools-mode allow-list, so the session resolves to the cli
        // default and the SDK gets the wrapped `[exec]` roster at init.
        const transportA = new StreamableHTTPClientTransport(new URL('/mcp', BASE_URL), {
            fetch: fetchViaApp,
            requestInit: {
                headers: {
                    Authorization: `Bearer ${TOKEN}`,
                    'x-anthropic-client': 'ClaudeCode',
                },
            },
        })
        const clientA = new Client({ name: 'Anthropic/ClaudeAI', version: '1.0.0' }, { capabilities: {} })
        await clientA.connect(transportA as ConnectableTransport)

        const sessionId = transportA.sessionId
        expect(sessionId).toBeTruthy()

        // Client caches the tools payload at init. cli mode collapses the wire
        // roster to the single `exec` umbrella tool (the sibling `render-ui` tool
        // is gated behind the `mcp-render-ui` flag, which is off in tests).
        const cachedTools = await clientA.listTools()
        expect(cachedTools.tools.map((t) => t.name).sort()).toEqual(['exec'])

        // headers_2 — pool member flipping to a different Anthropic vendor. The
        // vendor header never participates in tools-mode detection, so the request
        // stays in cli mode and the roster still collapses to the `exec` umbrella
        // tool.
        const pooledRoster = await listToolsOnSession(sessionId!, 'ClaudeAI')
        expect(pooledRoster.map((t) => t.name).sort()).toEqual(['exec'])

        await clientA.close()
    })

    it('tools init via the Cursor client name survives an Anthropic vendor flip on the same session', async () => {
        // Cursor pins tools mode through its self-reported clientInfo.name at init.
        // A later request on the pooled session carrying an Anthropic vendor header
        // must not flip the session to the cli default: `isToolsModeClient` reads
        // only the session-pinned client name and user-agent, never the vendor.
        const transport = new StreamableHTTPClientTransport(new URL('/mcp', BASE_URL), {
            fetch: fetchViaApp,
            requestInit: {
                headers: { Authorization: `Bearer ${TOKEN}` },
            },
        })
        const client = new Client({ name: 'cursor', version: '1.0.0' }, { capabilities: {} })
        await client.connect(transport as ConnectableTransport)

        const sessionId = transport.sessionId
        expect(sessionId).toBeTruthy()

        // Tools mode exposes the full multi-tool roster on the wire.
        const initRoster = await client.listTools()
        expect(initRoster.tools.length).toBeGreaterThan(1)
        expect(initRoster.tools.map((t) => t.name)).not.toContain('exec')

        // The vendor flip keeps the pinned tools mode.
        const pooledRoster = await listToolsOnSession(sessionId!, 'ClaudeCode')
        expect(pooledRoster.length).toBeGreaterThan(1)
        expect(pooledRoster.map((t) => t.name)).not.toContain('exec')

        await client.close()
    })
})
