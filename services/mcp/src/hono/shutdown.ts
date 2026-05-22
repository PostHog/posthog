import type { ServerType } from '@hono/node-server'
import type Redis from 'ioredis'

import type { Lifecycle } from './app'
import { shuttingDown as shuttingDownMetric } from './metrics'

const SHUTDOWN_GRACE_MS = parseInt(process.env.SHUTDOWN_GRACE_MS || '300000', 10)
const SHUTDOWN_PRESTOP_DELAY_MS = parseInt(process.env.SHUTDOWN_PRESTOP_DELAY_MS || '0', 10)

const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms))

export function registerShutdownHandlers(opts: {
    server: ServerType
    lifecycle: Lifecycle
    redis: InstanceType<typeof Redis>
}): void {
    const { server, lifecycle, redis } = opts
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
