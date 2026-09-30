import { serve } from '@hono/node-server'
import Redis from 'ioredis'
import { once } from 'node:events'
import type { AddressInfo } from 'node:net'

import { createApp } from '@/hono/app'

import { startSkillArchiveServer, type SkillArchiveServer } from './skill-archive'
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

    // ResourceCatalog snapshots this URL at construction. Keep the listener
    // bound during warmup so another process cannot claim its port.
    let fetchHandler: Parameters<typeof serve>[0]['fetch'] = () => new Response(null, { status: 503 })
    const server = serve({ fetch: (...args) => fetchHandler(...args), port: 0, hostname: '127.0.0.1' })
    await once(server, 'listening')
    const baseUrl = new URL(`http://127.0.0.1:${(server.address() as AddressInfo).port}`)
    process.env.MCP_APPS_BASE_URL = baseUrl.toString().replace(/\/$/, '')

    let redis: Awaited<ReturnType<typeof startTestRedis>> | undefined
    let skillArchive: SkillArchiveServer | undefined
    const stop = async (): Promise<void> => {
        await new Promise<void>((resolve) => server.close(() => resolve()))
        await skillArchive?.stop().catch(() => undefined)
        await redis?.quit().catch(() => undefined)
    }

    try {
        redis = await startTestRedis()
        skillArchive = await startSkillArchiveServer()
        // The dispatcher reads this when `createApp` constructs it.
        process.env.POSTHOG_MCP_SKILLS_URL = skillArchive.url
        const { app, warmup } = createApp(redis as unknown as Parameters<typeof createApp>[0])
        await warmup()
        fetchHandler = app.fetch
    } catch (err) {
        await stop()
        throw err
    }

    return { baseUrl, stop }
}
