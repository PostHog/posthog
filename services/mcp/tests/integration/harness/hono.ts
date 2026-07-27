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
// Integration test harness targets a local dev Redis; production paths set REDIS_URL.
// nosemgrep: trailofbits.generic.redis-unencrypted-transport.redis-unencrypted-transport
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
    process.env.POSTHOG_API_BASE_URL = env.apiBaseUrl

    // Start a temporary listener on port 0 to discover a free port, then
    // set MCP_APPS_BASE_URL before creating the app so the ResourceCatalog
    // (which snapshots env at construction time) sees the correct URL.
    const probe = serve({ fetch: () => new Response(), port: 0 })
    const probePort = (probe.address() as AddressInfo).port
    await new Promise<void>((resolve) => probe.close(() => resolve()))

    const baseUrl = new URL(`http://127.0.0.1:${probePort}`)
    process.env.MCP_APPS_BASE_URL = baseUrl.toString().replace(/\/$/, '')

    const redis = await startTestRedis()
    const { app, warmup } = createApp(redis as unknown as Parameters<typeof createApp>[0])
    await warmup()

    const server = serve({ fetch: app.fetch, port: probePort })

    return {
        baseUrl,
        stop: async () => {
            await new Promise<void>((resolve) => server.close(() => resolve()))
            await redis.quit().catch(() => undefined)
        },
    }
}
