import { serve } from '@hono/node-server'
import Redis from 'ioredis'
import type { AddressInfo } from 'node:net'

import { createApp } from '@/hono/app'

import type { IntegrationEnv, IntegrationHarness } from './types'

// Pinned test DB so we don't collide with the dev Redis (DB 0). Must be in
// 0–15 (Redis default DB count). FLUSHDB at boot is safe because the test
// owns this DB exclusively. Override via TEST_REDIS_DB if your local Redis is
// configured with a different db count.
const TEST_REDIS_DB = parseInt(process.env.TEST_REDIS_DB ?? '15', 10)
const TEST_REDIS_URL = process.env.TEST_REDIS_URL ?? process.env.REDIS_URL ?? 'redis://localhost:6379'

async function startTestRedis(): Promise<InstanceType<typeof Redis>> {
    const redis = new Redis(TEST_REDIS_URL, {
        db: TEST_REDIS_DB,
        lazyConnect: true,
        maxRetriesPerRequest: 1,
        connectTimeout: 2000,
    })
    try {
        await redis.connect()
    } catch (err) {
        await redis.quit().catch(() => undefined)
        throw new Error(
            `Hono integration harness needs Redis at ${TEST_REDIS_URL} (db ${TEST_REDIS_DB}). ` +
                `Boot the dev stack with \`./bin/start\`, or override TEST_REDIS_URL/TEST_REDIS_DB. Cause: ${String(err)}`
        )
    }
    await redis.flushdb()
    return redis
}

export async function startHonoHarness(env: IntegrationEnv): Promise<IntegrationHarness> {
    // Route the MCP server's outbound API traffic at the local PostHog stack.
    // `getBaseUrl()` checks `POSTHOG_API_BASE_URL` first and bypasses region detection.
    process.env.POSTHOG_API_BASE_URL = env.apiBaseUrl

    const redis = await startTestRedis()
    const { app } = createApp(redis as unknown as Parameters<typeof createApp>[0])
    const server = serve({ fetch: app.fetch, port: 0 })
    const address = server.address() as AddressInfo
    const baseUrl = new URL(`http://127.0.0.1:${address.port}`)

    // `getEnv()` reads MCP_APPS_BASE_URL on every HonoMcpServer init, so we can
    // set it after the listener has its port. Pointing at the harness's own
    // origin so `/ui-apps/<app>/main.js` resolves to this server's static route.
    process.env.MCP_APPS_BASE_URL = baseUrl.toString().replace(/\/$/, '')

    return {
        baseUrl,
        stop: async () => {
            await new Promise<void>((resolve) => server.close(() => resolve()))
            await redis.quit().catch(() => undefined)
        },
    }
}
