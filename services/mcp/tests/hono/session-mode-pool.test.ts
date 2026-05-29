// Verifies the connection-pooling scenario observed in production: Anthropic
// reuses a single `Mcp-Session-Id` across multiple inner clients (Claude
// Code, Claude.ai, Cowork) and differentiates them via the per-request
// `x-anthropic-client` header. The server caches the initial raw session
// identity hints and derives mode from those cached-first hints; a later
// `tools/call` carrying a different vendor must NOT flip the resolved
// mode/version.
//
// To probe the resolved mode DIRECTLY via a `tools/call` (the user flow
// under test) we exploit tools that are gated by `mcpVersion` in the catalog.
// The state resolver filters `state.allTools` by the resolved `version`
// (`tool-catalog.ts:161-163`), and `handleToolCall` returns the guard
// "Tool <name> not found" (`tool-executor.ts:78-80`) when the requested
// tool is absent from `state.allTools`.
//
// cli mode pins `version=2`. A v2-only tool (e.g. `query-session-recordings-list`)
// is present iff this request resolved to v2; a v1-only tool
// (e.g. `accounts-list`) is absent iff this request resolved to v2.
//
// If cli mode survives the vendor flip on the pooled session, calling the
// v2-only tool dispatches (any non-"not found" response) and calling the
// v1-only tool returns the missing-tool guard. If mode flipped to v1, both
// outcomes reverse. That's a direct observable for "the resolved mode at
// headers_2 equals the resolved mode at headers_1".
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

// Tools chosen as version-specific probes (see file header for rationale).
const V1_ONLY_TOOL = 'accounts-list'
const V2_ONLY_TOOL = 'query-session-recordings-list'

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

interface ToolCallResponse {
    result?: { content?: Array<{ type: string; text: string }>; isError?: boolean }
}

async function callToolOnSession(sessionId: string, vendorClient: string, toolName: string): Promise<ToolCallResponse> {
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
            id: 'pool-tools-call',
            method: 'tools/call',
            params: { name: toolName, arguments: {} },
        }),
    })
    expect(res.status).toBe(200)
    return (await res.json()) as ToolCallResponse
}

function firstText(resp: ToolCallResponse): string {
    return resp.result?.content?.[0]?.text ?? ''
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
        // roster to a single `exec`.
        const cachedTools = await clientA.listTools()
        expect(cachedTools.tools).toHaveLength(1)
        expect(cachedTools.tools[0]!.name).toBe('exec')

        // headers_2 — pool member with a non-coding-agent vendor. If the
        // resolver re-derives mode from the live request, `vendorClient='ClaudeAI'`
        // + cached `clientName='Anthropic/ClaudeAI'` both miss the coding-agent
        // fragments -> resolves to tools mode (v1) -> the v2-only tool falls out
        // of `state.allTools` and the dispatcher returns "not found". With the
        // initial vendor hint cached, the request stays at v2 and the v2-only
        // tool dispatches.
        const probe = await callToolOnSession(sessionId!, 'ClaudeAI', V2_ONLY_TOOL)
        expect(firstText(probe)).not.toMatch(new RegExp(`Tool ${V2_ONLY_TOOL} not found`, 'i'))

        // Symmetric negative probe: a v1-only tool must STILL be absent under
        // the preserved cli/v2 mode.
        const negative = await callToolOnSession(sessionId!, 'ClaudeAI', V1_ONLY_TOOL)
        expect(negative.result?.isError).toBe(true)
        expect(firstText(negative)).toMatch(new RegExp(`Tool ${V1_ONLY_TOOL} not found`, 'i'))

        await clientA.close()
    })
})
