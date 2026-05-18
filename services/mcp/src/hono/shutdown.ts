import type Redis from 'ioredis'
import type { Server } from 'node:http'

import type { Lifecycle } from './app'
import { shuttingDown as shuttingDownMetric } from './metrics'
import type { SessionStore } from './session-store'

const SHUTDOWN_GRACE_MS = parseInt(process.env.SHUTDOWN_GRACE_MS || '30000', 10)
const SHUTDOWN_PRESTOP_DELAY_MS = parseInt(process.env.SHUTDOWN_PRESTOP_DELAY_MS || '5000', 10)

const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms))

export function registerShutdownHandlers(opts: {
    server: Server
    store: SessionStore
    lifecycle: Lifecycle
    redis: Redis
}): void {
    const { server, store, lifecycle, redis } = opts
    let shuttingDown = false

    const shutdown = async (signal: string): Promise<void> => {
        if (shuttingDown) {
            return
        }
        shuttingDown = true
        console.info(`[MCP] ${signal} received — shutting down`)

        lifecycle.shuttingDown = true
        shuttingDownMetric.set(1)

        const shutdownStart = Date.now()
        if (SHUTDOWN_PRESTOP_DELAY_MS > 0) {
            await sleep(SHUTDOWN_PRESTOP_DELAY_MS)
        }

        const drainBudget = Math.max(SHUTDOWN_GRACE_MS - (Date.now() - shutdownStart), 1000)
        const closed = new Promise<void>((resolve) => server.close(() => resolve()))
        await Promise.race([closed, sleep(drainBudget)])

        store.stopGc()
        store.closeAll()

        try {
            await redis.quit()
        } catch (err) {
            console.error('[MCP] Redis quit failed:', err)
        }

        process.exit(0)
    }

    process.on('SIGTERM', () => void shutdown('SIGTERM'))
    process.on('SIGINT', () => void shutdown('SIGINT'))
}
