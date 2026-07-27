// Entry point for the agent-proxy Hono server.
//
// Startup sequence:
//   1. Load and validate configuration from environment variables.
//   2. Connect to Redis (eager connect with retry).
//   3. Import and cache the RS256 public key.
//   4. Create the Hono app.
//   5. Start the HTTP server on PORT (default 8003).
//   6. Register SIGTERM/SIGINT shutdown handlers (drain in-flight SSE, quit Redis).

import { serve } from '@hono/node-server'
import Redis from 'ioredis'

import { loadConfig } from '../lib/config.js'
import { loadPublicKeys } from '../lib/jwt.js'
import { logger } from '../lib/logging.js'
import { createApp } from './app.js'
import { registerShutdownHandlers } from './shutdown.js'

async function main(): Promise<void> {
    const config = loadConfig()

    // nosemgrep: trailofbits.generic.redis-unencrypted-transport.redis-unencrypted-transport
    const redis = new Redis(config.redisUrl, {
        lazyConnect: true,
        maxRetriesPerRequest: 3,
        enableOfflineQueue: false,
        connectTimeout: 5000,
        commandTimeout: 2000,
        keepAlive: 30000,
        retryStrategy: (times: number) => Math.min(times * 200, 2000),
    })

    redis.on('error', (err: Error) => {
        logger.error('redis:error', { error: err.message })
    })

    redis.on('connect', () => {
        logger.info('redis:connected', {})
    })

    try {
        await redis.connect()
    } catch (err) {
        logger.error('redis:connect_failed', { error: err instanceof Error ? err.message : String(err) })
        process.exit(1)
    }

    let publicKeys: globalThis.CryptoKey[]
    try {
        publicKeys = await loadPublicKeys(config.sandboxJwtPublicKeysPem)
    } catch (err) {
        logger.error('jwt:public_key_load_failed', { error: err instanceof Error ? err.message : String(err) })
        process.exit(1)
    }

    const { app, lifecycle } = createApp(redis, config, publicKeys)

    const server = serve(
        {
            fetch: app.fetch,
            port: config.port,
            hostname: config.host,
            serverOptions: { requestTimeout: 0 },
        },
        (info) => {
            logger.info('server:started', { host: config.host, port: info.port })
        }
    )

    registerShutdownHandlers({
        server,
        lifecycle,
        redis,
        shutdownGraceMs: config.shutdownGraceMs,
        shutdownPrestopDelayMs: config.shutdownPrestopDelayMs,
    })
}

main().catch((err) => {
    logger.error('fatal', { error: err instanceof Error ? err.message : String(err) })
    process.exit(1)
})
