import { setupServer } from 'msw/node'
import { afterAll, beforeAll } from 'vitest'

import { createApp } from '@/hono/app'
import type { RedisLike } from '@/hono/cache/RedisCache'

import { defineMcpProtocolTests } from '../integration/mcp-protocol-suite'
import { handlers } from '../workers/fixtures/handlers'

// MSW intercepts the outbound PostHog API traffic the MCP server makes during
// init() and tool calls, serving fixtures from the same set the workers harness
// uses. Requests to our in-process Hono `app` go through `app.request()` and
// don't touch globalThis.fetch, so we don't need a localhost passthrough rule.
const mswServer = setupServer(...handlers)

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
            return [cur === '0' ? 'next' : '0', cur === '0' ? Array.from(store.keys()) : []] as [
                string,
                string[],
            ]
        },
        ping: async () => 'PONG',
    }
}

let app: ReturnType<typeof createApp>

beforeAll(() => {
    process.env.TEST = '1'
    mswServer.listen({ onUnhandledRequest: 'bypass' })
    app = createApp(createInMemoryRedis())
})

afterAll(() => {
    mswServer.close()
})

// Custom fetch that routes through the Hono app's `request()` entry point —
// the same WHATWG Request/Response pipeline the runtime uses, minus the TCP
// socket. Keeps the test fully in-process so no port management or shutdown
// races; still exercises every middleware, route, and the MCP transport.
const fetchViaApp: typeof fetch = (input, init) => {
    const url = input instanceof URL ? input : new URL(typeof input === 'string' ? input : input.url)
    return app.request(url.pathname + url.search, init ?? {})
}

defineMcpProtocolTests('Hono', () => ({
    // baseUrl host is irrelevant — `fetchViaApp` extracts only path + query.
    baseUrl: new URL('http://hono.test'),
    fetch: fetchViaApp,
    token: 'phx_integration_test_token',
}))
