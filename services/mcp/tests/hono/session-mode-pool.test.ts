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
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, beforeAll, describe, expect, it } from 'vitest'

import { createApp } from '@/hono/app'
import type { RedisLike } from '@/hono/cache/RedisCache'
import { MCP_CURSOR_EXEC_MODE_FLAG } from '@/hono/constants'

import project from '../workers/fixtures/api_projects_id.json'
import { contextMillHandler, handlers } from '../workers/fixtures/handlers'
import { makeRedisRateLimitStubs } from './helpers/redis-rate-limit-stubs'

const mswServer = setupServer(
    ...handlers,
    contextMillHandler,
    http.get('*/api/organizations/:orgId/projects/:projectId/', () => HttpResponse.json(project))
)

function createInMemoryRedis(): RedisLike & {
    ping(): Promise<string>
    incrby(key: string, increment: number): Promise<number>
} {
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
        ...makeRedisRateLimitStubs(store),
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

interface RpcResponse {
    result?: {
        tools?: Array<{ name: string }>
        content?: Array<{ type: string; text?: string }>
        isError?: boolean
    }
}

const CURSOR_EXEC_MODE_ON = { 'x-posthog-flag-overrides': JSON.stringify({ [MCP_CURSOR_EXEC_MODE_FLAG]: true }) }

async function rpcOnSession(
    sessionId: string,
    method: string,
    params: Record<string, unknown>,
    headers: Record<string, string>
): Promise<NonNullable<RpcResponse['result']>> {
    const res = await fetchViaApp(new URL('/mcp', BASE_URL), {
        method: 'POST',
        headers: {
            Authorization: `Bearer ${TOKEN}`,
            'Content-Type': 'application/json',
            Accept: 'application/json, text/event-stream',
            'Mcp-Session-Id': sessionId,
            ...headers,
        },
        body: JSON.stringify({ jsonrpc: '2.0', id: `pool-${method}`, method, params }),
    })
    expect(res.status).toBe(200)
    const json = (await res.json()) as RpcResponse
    return json.result ?? {}
}

async function listToolsOnSession(sessionId: string, vendorClient: string): Promise<Array<{ name: string }>> {
    const result = await rpcOnSession(sessionId, 'tools/list', {}, { 'x-anthropic-client': vendorClient })
    return result.tools ?? []
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
        // only advertises to MCP Apps hosts; Claude Code isn't one).
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

    async function connectCursor(headers: Record<string, string> = {}): Promise<{ client: Client; sessionId: string }> {
        const transport = new StreamableHTTPClientTransport(new URL('/mcp', BASE_URL), {
            fetch: fetchViaApp,
            requestInit: { headers: { Authorization: `Bearer ${TOKEN}`, ...headers } },
        })
        const client = new Client({ name: 'cursor', version: '1.0.0' }, { capabilities: {} })
        await client.connect(transport as ConnectableTransport)
        expect(transport.sessionId).toBeTruthy()
        return { client, sessionId: transport.sessionId! }
    }

    it('moves a live Cursor session to cli when the flag turns on, and still serves its per-tool roster', async () => {
        const { client, sessionId } = await connectCursor()
        const cachedRoster = await client.listTools()
        expect(cachedRoster.tools.map((t) => t.name)).toContain('project-get')

        const roster = await rpcOnSession(sessionId, 'tools/list', {}, CURSOR_EXEC_MODE_ON)
        expect(roster.tools?.map((t) => t.name)).toEqual(['exec'])

        const call = await rpcOnSession(
            sessionId,
            'tools/call',
            { name: 'project-get', arguments: {} },
            CURSOR_EXEC_MODE_ON
        )
        expect(call.isError).toBeFalsy()
        expect(call.content?.[0]?.text).toContain(project.name)

        await client.close()
    })

    it('still serves exec to a Cursor session when the flag turns off again', async () => {
        const { client, sessionId } = await connectCursor(CURSOR_EXEC_MODE_ON)
        const cachedRoster = await client.listTools()
        expect(cachedRoster.tools.map((t) => t.name)).toEqual(['exec'])

        const call = await rpcOnSession(
            sessionId,
            'tools/call',
            { name: 'exec', arguments: { command: 'search project-get' } },
            {}
        )
        expect(call.isError).toBeFalsy()
        expect(call.content?.[0]?.text).toContain('project-get')

        await client.close()
    })
})
