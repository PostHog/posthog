import { serve } from '@hono/node-server'
import type { AddressInfo } from 'node:net'

import { createApp } from '@/hono/app'
import type { RedisLike } from '@/hono/cache/RedisCache'

import type { IntegrationEnv, IntegrationHarness } from './types'

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

export async function startHonoHarness(env: IntegrationEnv): Promise<IntegrationHarness> {
    // Route the MCP server's outbound API traffic at the local PostHog stack.
    // `getBaseUrl()` checks `POSTHOG_API_BASE_URL` first and bypasses region detection.
    process.env.POSTHOG_API_BASE_URL = env.apiBaseUrl

    const app = createApp(createInMemoryRedis())
    const server = serve({ fetch: app.fetch, port: 0 })
    const address = server.address() as AddressInfo
    const baseUrl = new URL(`http://127.0.0.1:${address.port}`)

    // `getEnv()` reads MCP_APPS_BASE_URL on every HonoMcpServer init, so we can
    // set it after the listener has its port. Pointing at the harness's own
    // origin so `/ui-apps/<app>/main.js` resolves to this server's static route.
    process.env.MCP_APPS_BASE_URL = baseUrl.toString().replace(/\/$/, '')

    return {
        baseUrl,
        stop: () => new Promise<void>((resolve) => server.close(() => resolve())),
    }
}
