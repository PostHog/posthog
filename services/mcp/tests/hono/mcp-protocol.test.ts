import { setupServer } from 'msw/node'
import { afterAll, beforeAll, describe, expect, it } from 'vitest'

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

describe('/agent endpoint', () => {
    async function listToolNames(path: string): Promise<string[]> {
        const res = await app.request(path, {
            method: 'POST',
            headers: {
                Authorization: 'Bearer phx_integration_test_token',
                'Content-Type': 'application/json',
                Accept: 'application/json, text/event-stream',
                'x-posthog-mcp-mode': 'tools',
                'x-posthog-flag-overrides': JSON.stringify({ 'posthog-agent-mcp': true }),
            },
            body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/list' }),
        })
        const body = (await res.json()) as { result: { tools: Array<{ name: string }> } }
        return body.result.tools.map((tool) => tool.name)
    }

    it('serves exactly the PostHog Agent tools, and /mcp does not serve them', async () => {
        const agentTools = await listToolNames('/agent')
        const mainTools = await listToolNames('/mcp')

        expect(agentTools.sort()).toEqual(
            ['posthog-agent-cancel', 'posthog-agent-reply', 'posthog-agent-run', 'posthog-agent-status'].sort()
        )
        expect(mainTools.length).toBeGreaterThan(10)
        expect(mainTools.filter((name) => name.startsWith('posthog-agent-'))).toEqual([])
    })
})
