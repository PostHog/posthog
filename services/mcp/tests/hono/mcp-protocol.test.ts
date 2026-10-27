import { setupServer } from 'msw/node'
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest'

import { createApp } from '@/hono/app'
import type { RedisLike } from '@/hono/cache/RedisCache'

import {
    defineAuthTests,
    defineCatalogFilterTests,
    defineExecModeTests,
    defineHttpRouteTests,
    defineJsonRpcEdgeCaseTests,
    defineMcpProtocolTests,
    defineResilienceTests,
    defineResourceCatalogTests,
    defineSessionLifecycleTests,
    defineSessionTrackingTests,
    defineStatelessProtocolTests,
    type ProtocolTestHarness,
} from '../integration/mcp-protocol-suite'
import { handlers, contextMillHandler } from '../workers/fixtures/handlers'
import { makeRedisRateLimitStubs } from './helpers/redis-rate-limit-stubs'

const mswServer = setupServer(...handlers, contextMillHandler)

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

const harness = (): ProtocolTestHarness => ({
    baseUrl: new URL('http://hono.test'),
    fetch: fetchViaApp,
    token: 'phx_integration_test_token',
    stateless: true,
    gracefulUnknown: true,
    publicRoutes: true,
})

defineMcpProtocolTests('Hono', harness)
defineResilienceTests('Hono', harness)
defineHttpRouteTests('Hono', harness)
defineAuthTests('Hono', harness)
defineJsonRpcEdgeCaseTests('Hono', harness)
defineSessionLifecycleTests('Hono', harness)
defineResourceCatalogTests('Hono', harness)
defineCatalogFilterTests('Hono', harness)
defineExecModeTests('Hono', harness)
defineSessionTrackingTests('Hono', harness)
defineStatelessProtocolTests('Hono', harness)

describe('Hono request body limit', () => {
    it('stops reading a streamed body once it passes the size cap, and logs the rejection', async () => {
        const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
        const chunk = new Uint8Array(256 * 1024).fill(0x20)
        let sent = 0
        const body = new ReadableStream<Uint8Array>({
            pull(controller) {
                // A reader that buffers the whole body reaches this error, and the request fails with a 500.
                if (sent === 16) {
                    controller.error(new Error('read past the size cap'))
                    return
                }
                sent += 1
                controller.enqueue(chunk)
            },
        })
        const res = await fetchViaApp(new URL('/mcp', 'http://hono.test'), {
            method: 'POST',
            headers: {
                Authorization: 'Bearer phx_integration_test_token',
                'Content-Type': 'application/json',
                Accept: 'application/json, text/event-stream',
            },
            body,
            duplex: 'half',
        } as RequestInit)

        expect(res.status).toBe(200)
        expect(await res.json()).toMatchObject({ error: { code: -32600 } })
        expect(warn).toHaveBeenCalledWith('[RequestBody] body too large', expect.stringContaining('"token":"****oken"'))
        warn.mockRestore()
    })
})
