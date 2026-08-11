// Entry point for the integration-service.

import { S3Client } from '@aws-sdk/client-s3'
import { serve } from '@hono/node-server'
import type { Pool } from 'pg'

import { JwtVerifier } from './auth/jwt.js'
import { SigningKeyLoader } from './auth/registry.js'
import { credentialProvider } from './aws/credentials.js'
import { createPool, observeVersion } from './db/client.js'
import { createApp, type Lifecycle } from './http/app.js'
import { loadConfig } from './lib/config.js'
import { logger } from './lib/logging.js'
import { scheduleJittered } from './lib/schedule.js'
import { SnapshotManager } from './snapshot.js'
import { createFileStore } from './store/fileStore.js'
import { UsagePublisher } from './usage/publisher.js'
import { UsageRecorder } from './usage/recorder.js'

async function main(): Promise<void> {
    const config = loadConfig()

    let pool: Pool | undefined
    if (config.databaseUrl) {
        try {
            pool = await createPool(config.databaseUrl)
            logger.info('db:connected', {})
        } catch (err) {
            // Guarded in loadConfig for production. Locally the service runs without usage
            // recording, which costs the rollup and nothing else.
            logger.error('db:connect_failed', { error: err instanceof Error ? err.message : String(err) })
            process.exit(1)
        }
    } else {
        logger.warn('db:disabled', { reason: 'INTEGRATION_SERVICE_DATABASE_URL is unset, so no usage recording' })
    }

    const signingKeys = new SigningKeyLoader(config.secretsDir)
    try {
        await signingKeys.load()
    } catch (err) {
        logger.error('startup:signing_keys_load_failed', {
            dir: config.secretsDir,
            error: err instanceof Error ? err.message : String(err),
        })
        process.exit(1)
    }

    const store = createFileStore({
        dir: config.secretsDir,
        // Without Postgres there is no shared record of when content first appeared, so the
        // retirement verdict simply stays false rather than guessing.
        observeVersion: (hash) => (pool ? observeVersion(pool, hash) : Promise.resolve(null)),
    })

    const recorder = new UsageRecorder({ pool })
    const lifecycle: Lifecycle = { shuttingDown: false, ready: false }
    const snapshots = new SnapshotManager({ store, lifecycle, dir: config.secretsDir })

    const app = createApp({
        verifier: new JwtVerifier(signingKeys),
        lifecycle,
        resolveDeps: { loadSecrets: () => Promise.resolve(snapshots.current()), recorder },
        metricsToken: config.metricsToken,
    })

    await snapshots.reload()
    if (!lifecycle.ready) {
        logger.error('startup:no_credentials_on_mount', { dir: config.secretsDir })
    }

    const server = serve({ fetch: app.fetch, port: config.port, hostname: config.host }, (info) => {
        logger.info('server:started', { host: config.host, port: info.port, env: config.env })
    })

    scheduleJittered(config.reloadSeconds * 1000, async () => {
        await snapshots.reload()
        await signingKeys.reload()
    })

    scheduleJittered(config.usageFlushMs, () => recorder.flush())
    scheduleJittered(24 * 60 * 60 * 1000, () => recorder.prune(config.retentionDays))

    if (config.usageBucket) {
        const publisher = new UsagePublisher({
            s3: new S3Client({
                region: config.awsRegion,
                // Explicit, so the SDK never consults its default chain (aws/credentials.ts).
                credentials: credentialProvider(),
                ...(config.awsEndpoint ? { endpoint: config.awsEndpoint, forcePathStyle: true } : {}),
            }),
            bucket: config.usageBucket,
            kmsKeyId: config.usageKmsKeyId,
            env: config.env,
            quietWindowHours: config.retireQuietHours,
            recorder,
            loadSnapshot: () => Promise.resolve(snapshots.current()),
        })
        scheduleJittered(config.usagePublishIntervalMs, () => publisher.publish())
    }

    registerShutdown({ server, lifecycle, recorder, pool, config })
}

function registerShutdown(opts: {
    server: { close: (cb: () => void) => void }
    lifecycle: Lifecycle
    recorder: UsageRecorder
    pool: Pool | undefined
    config: { shutdownGraceMs: number; shutdownPrestopDelayMs: number }
}): void {
    let started = false
    const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms))

    const shutdown = async (signal: string): Promise<void> => {
        if (started) {
            return
        }
        started = true
        logger.info('shutdown:start', { signal })
        opts.lifecycle.shuttingDown = true

        const startedAt = Date.now()
        if (opts.config.shutdownPrestopDelayMs > 0) {
            await sleep(opts.config.shutdownPrestopDelayMs)
        }
        const drainBudget = Math.max(opts.config.shutdownGraceMs - (Date.now() - startedAt), 1000)
        await Promise.race([new Promise<void>((resolve) => opts.server.close(() => resolve())), sleep(drainBudget)])

        // Write what accumulated since the last flush, so a rolling restart does not lose
        // the reads that prove a caller has moved onto a new value.
        await opts.recorder.flush()
        if (opts.pool) {
            await opts.pool.end().catch((err: unknown) => {
                logger.error('shutdown:db_close_failed', {
                    error: err instanceof Error ? err.message : String(err),
                })
            })
        }
        logger.info('shutdown:complete', {})
        process.exit(0)
    }

    process.on('SIGTERM', () => void shutdown('SIGTERM'))
    process.on('SIGINT', () => void shutdown('SIGINT'))
}

main().catch((err: unknown) => {
    logger.error('fatal', { error: err instanceof Error ? err.message : String(err) })
    process.exit(1)
})
