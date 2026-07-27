// Graceful shutdown handler for the agent-proxy Hono server.
//
// Registers SIGTERM and SIGINT handlers that:
//   1. Optionally wait for a prestop delay (Kubernetes lifecycle hook window).
//   2. Drain in-flight SSE connections up to the grace budget.
//   3. Quit the shared Redis client.
//   4. Exit with code 0.

import type { ServerType } from '@hono/node-server'
import type { Redis } from 'ioredis'

import { logger } from '../lib/logging.js'
import { shuttingDown as shuttingDownGauge } from './metrics.js'
import type { Lifecycle } from './types.js'

function sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms))
}

export function registerShutdownHandlers(opts: {
    server: ServerType
    lifecycle: Lifecycle
    redis: InstanceType<typeof Redis>
    shutdownGraceMs: number
    shutdownPrestopDelayMs: number
}): void {
    const { server, lifecycle, redis, shutdownGraceMs, shutdownPrestopDelayMs } = opts
    let alreadyShuttingDown = false

    const shutdown = async (signal: string): Promise<void> => {
        if (alreadyShuttingDown) {
            return
        }
        alreadyShuttingDown = true
        logger.info('shutdown:start', { signal })

        lifecycle.shuttingDown = true
        shuttingDownGauge.set(1)

        const shutdownStart = Date.now()
        if (shutdownPrestopDelayMs > 0) {
            await sleep(shutdownPrestopDelayMs)
        }

        // Drain in-flight requests (SSE connections) up to the grace budget.
        const drainBudget = Math.max(shutdownGraceMs - (Date.now() - shutdownStart), 1000)
        const closed = new Promise<void>((resolve) => server.close(() => resolve()))
        await Promise.race([closed, sleep(drainBudget)])

        try {
            await redis.quit()
        } catch (err) {
            logger.error('shutdown:redis_quit_failed', { error: err instanceof Error ? err.message : String(err) })
        }

        logger.info('shutdown:complete', {})
        process.exit(0)
    }

    process.on('SIGTERM', () => void shutdown('SIGTERM'))
    process.on('SIGINT', () => void shutdown('SIGINT'))
}
