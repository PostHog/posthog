// Verifies the connection-pooling scenario observed in production: Anthropic
// reuses a single `Mcp-Session-Id` across multiple inner clients (Claude
// Code, Claude.ai, Cowork) and differentiates them via the per-request
// `x-anthropic-client` header. The server caches the initial raw session
// identity hints and derives mode from those cached-first hints; a later
// `tools/call` carrying a different vendor must NOT flip the resolved
// mode/version.
//
// To probe the resolved mode DIRECTLY we issue a raw `tools/list` on the pooled
// session: cli (single-exec) mode collapses the wire roster to a single `exec`
// tool, while tools mode exposes the full multi-tool roster. If cli mode
// survives the vendor flip, a `tools/list` carrying the flipped vendor still
// returns just `[exec]`; if mode flipped to tools, it would return the full
// roster. That's a direct observable for "the resolved mode at headers_2 equals
// the resolved mode at headers_1".
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
    it('cli init via x-anthropic-client survives a non-coding-agent vendor on the same session', async () => {
        // headers_1 — clientInfo.name is the new Claude Desktop-style vendor-prefixed
        // shape (NOT a coding-agent fragment), while the per-request vendor header
        // identifies the inner client as Claude Code. This is the production-pool
        // scenario where the body identifies the transport-owner and the header
        // identifies the live consumer.
        //
        // Without reading the vendor header, the resolver picks tools mode at
        // init (because `Anthropic/ClaudeAI` doesn't match any coding-agent
        // fragment) and the SDK gets the full multi-tool roster. With vendor
        // reading + cached session hints, the resolver picks cli mode at init
        // and the SDK gets the wrapped `[exec]` roster.
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

        // headers_2 — pool member flipping to a different Anthropic vendor.
        // `ClaudeAI` is itself an Anthropic client, so it resolves to cli mode on
        // its own merits; combined with the cached session hints from init, the
        // request stays in cli mode and the roster still collapses to the `exec`
        // umbrella tool. Every Anthropic vendor (the `x-anthropic-client` header)
        // runs in cli mode, so no pooled vendor flip can downgrade to tools mode.
        const pooledRoster = await listToolsOnSession(sessionId!, 'ClaudeAI')
        expect(pooledRoster.map((t) => t.name).sort()).toEqual(['exec'])

        await clientA.close()
    })
})
