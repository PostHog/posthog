// Verifies the connection-pooling scenario observed in production: Anthropic
// reuses a single `Mcp-Session-Id` across multiple inner clients (Claude
// Code, Claude.ai, Cowork) and differentiates them via the per-request
// `x-anthropic-client` header. The server pins `mcpMode` in the session cache
// at `initialize` and must not flip mode mid-session when the live vendor
// changes. Observable signal: the tool roster size returned by `tools/list`.
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

interface ToolListResponse {
    result?: { tools?: Array<{ name: string }> }
}

async function postToolsListOnSession(sessionId: string, vendorClient: string): Promise<ToolListResponse> {
    const res = await fetchViaApp(new URL('/mcp', BASE_URL), {
        method: 'POST',
        headers: {
            Authorization: `Bearer ${TOKEN}`,
            'Content-Type': 'application/json',
            Accept: 'application/json, text/event-stream',
            'Mcp-Session-Id': sessionId,
            'x-anthropic-client': vendorClient,
        },
        body: JSON.stringify({ jsonrpc: '2.0', id: 'pool-tools-list', method: 'tools/list' }),
    })
    expect(res.status).toBe(200)
    return (await res.json()) as ToolListResponse
}

describe('Session mode survives a pooled-transport vendor flip', () => {
    it('keeps cli mode (1 tool) when a non-coding-agent reuses the session id', async () => {
        // Client A — Claude Code: clientInfo.name=claude-code + x-anthropic-client=ClaudeCode.
        // The server should pin mcpMode='cli' in the session cache during initialize.
        const transportA = new StreamableHTTPClientTransport(new URL('/mcp', BASE_URL), {
            fetch: fetchViaApp,
            requestInit: {
                headers: {
                    Authorization: `Bearer ${TOKEN}`,
                    'x-anthropic-client': 'ClaudeCode',
                },
            },
        })
        const clientA = new Client({ name: 'claude-code', version: '1.0.0' }, { capabilities: {} })
        await clientA.connect(transportA as ConnectableTransport)

        const sessionId = transportA.sessionId
        expect(sessionId).toBeTruthy()

        const a = await clientA.listTools()
        expect(a.tools).toHaveLength(1)
        expect(a.tools[0]!.name).toBe('exec')

        // Client B — emulates Claude.ai / Cowork carrying a tools/list on the same
        // pooled session id. Raw JSON-RPC because there is no second initialize:
        // the pool member piggybacks on A's existing transport from the server's POV.
        const pool = await postToolsListOnSession(sessionId!, 'ClaudeAI')
        expect(pool.result?.tools).toHaveLength(1)
        expect(pool.result!.tools![0]!.name).toBe('exec')

        await clientA.close()
    })

    it('keeps tools mode (>1 tools) when a coding-agent reuses a Desktop-pooled session id', async () => {
        // Client A — Claude Desktop: clientInfo.name='Anthropic/ClaudeAI' (the new
        // vendor-prefixed shape) and no x-anthropic-client on initialize, mirroring
        // the production logs. mcpMode should pin to 'tools'.
        const transportA = new StreamableHTTPClientTransport(new URL('/mcp', BASE_URL), {
            fetch: fetchViaApp,
            requestInit: { headers: { Authorization: `Bearer ${TOKEN}` } },
        })
        const clientA = new Client({ name: 'Anthropic/ClaudeAI', version: '1.0.0' }, { capabilities: {} })
        await clientA.connect(transportA as ConnectableTransport)

        const sessionId = transportA.sessionId
        expect(sessionId).toBeTruthy()

        const a = await clientA.listTools()
        expect(a.tools.length).toBeGreaterThan(1)
        const baselineCount = a.tools.length

        // Client B — emulates a ClaudeCode-flavored inner request landing on the
        // Desktop pool. Without session-mode pinning, this would resolve as
        // coding-agent and collapse the roster to just `exec`.
        const pool = await postToolsListOnSession(sessionId!, 'ClaudeCode')
        expect(pool.result?.tools).toBeTruthy()
        expect(pool.result!.tools!.length).toBe(baselineCount)

        await clientA.close()
    })
})
