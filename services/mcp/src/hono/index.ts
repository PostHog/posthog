import { serve } from '@hono/node-server'
// ioredis v4 is CJS with `module.exports.default = Redis` and no named `Redis`
// export. Use the default import so esbuild's CJS-in-ESM interop resolves the
// constructor when this file is bundled into a single .mjs.
import Redis from 'ioredis'

import { createApp } from './app'
import { shuttingDown as shuttingDownMetric } from './metrics'

const PORT = parseInt(process.env.PORT || '3001', 10)
const HOST = process.env.HOST || '0.0.0.0'

// Drain budget on SIGTERM. Must be < terminationGracePeriodSeconds (chart sets
// 60s) with margin for Redis quit + final exit.
const SHUTDOWN_GRACE_MS = parseInt(process.env.SHUTDOWN_GRACE_MS || '30000', 10)
// Brief delay after SIGTERM before we close the listener, so kube-proxy has
// time to remove this pod from the service endpoints. Skip when a `preStop`
// hook handles the wait.
const SHUTDOWN_PRESTOP_DELAY_MS = parseInt(process.env.SHUTDOWN_PRESTOP_DELAY_MS || '5000', 10)

function resolveRedisUrl(): string {
    const url = process.env.REDIS_URL
    if (url) {
        return url
    }
    if (process.env.NODE_ENV === 'production') {
        console.error('[MCP] REDIS_URL is required in production')
        process.exit(1)
    }
    return 'redis://localhost:6379'
}

const redis = new Redis(resolveRedisUrl(), {
    lazyConnect: true,
    maxRetriesPerRequest: 3,
    // Fail fast when the connection isn't healthy: don't accumulate commands in
    // an offline queue (caller gets an error and a clean retry path), bound
    // every command, and keep TCP alive so idle Redis hops drop us instead of
    // silently wedging. Hot-path requests hit Redis on every cache read/write,
    // so a stalled Redis would otherwise turn into a fleet-wide outage.
    enableOfflineQueue: false,
    connectTimeout: 5000,
    commandTimeout: 2000,
    keepAlive: 30000,
    retryStrategy: (times: number) => Math.min(times * 200, 2000),
})

redis.on('error', (err: Error) => {
    console.error('[MCP] Redis connection error:', err.message)
})

redis.on('connect', () => {
    console.info('[MCP] Redis connected')
})

const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms))

async function main(): Promise<void> {
    try {
        await redis.connect()
    } catch (err) {
        console.error('[MCP] Failed to connect to Redis:', err)
        process.exit(1)
    }

    const { app, store, lifecycle } = createApp(redis as unknown as Parameters<typeof createApp>[0])

    const server = serve({ fetch: app.fetch, port: PORT, hostname: HOST }, (info) => {
        console.info(`[MCP] Server started on ${HOST}:${info.port}`)
    })

    let shuttingDown = false
    const shutdown = async (signal: string): Promise<void> => {
        if (shuttingDown) {
            return
        }
        shuttingDown = true
        console.info(`[MCP] ${signal} received — shutting down`)

        // Step 1: flip /readyz to 503 and refuse new sessions. This kicks off
        // kube-proxy's removal of the pod from the service endpoints.
        lifecycle.shuttingDown = true
        shuttingDownMetric.set(1)

        // Step 2: give kube-proxy a head start (skip if a preStop hook handles it).
        if (SHUTDOWN_PRESTOP_DELAY_MS > 0) {
            await sleep(SHUTDOWN_PRESTOP_DELAY_MS)
        }

        // Step 3: stop accepting new TCP connections. Existing keep-alive
        // connections (and in-flight responses on them) keep running.
        const drainStart = Date.now()
        const drainBudget = Math.max(SHUTDOWN_GRACE_MS - (Date.now() - drainStart), 1000)
        const closed = new Promise<void>((resolve) => server.close(() => resolve()))
        await Promise.race([closed, sleep(drainBudget)])

        // Step 4: anything still active gets force-closed. Clients see the
        // stream end and re-`initialize` against the next pod via the standard
        // 404→re-init flow in the MCP Streamable HTTP spec.
        store.closeAll()

        try {
            await redis.quit()
        } catch (err) {
            console.error('[MCP] Redis quit failed:', err)
        }

        process.exit(0)
    }

    process.on('SIGTERM', () => {
        void shutdown('SIGTERM')
    })
    process.on('SIGINT', () => {
        void shutdown('SIGINT')
    })
}

main().catch((err) => {
    console.error('[MCP] Fatal error:', err)
    process.exit(1)
})
