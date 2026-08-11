// Wires the service together and owns its lifecycle.
//
// Shutdown ordering is fixed: mark draining, wait out the prestop delay, drain the HTTP
// server, flush the usage recorder, end the pool. The flush sits after the drain so
// in-flight requests still record, and before the pool closes so it has somewhere to
// write. unhandledRejection and uncaughtException route through the same path, so a crash
// still flushes the reads that prove a caller has moved onto a new value.

import { S3Client } from '@aws-sdk/client-s3'
import { serve } from '@hono/node-server'
import type { Hono } from 'hono'
import type { Pool } from 'pg'

import { JwtVerifier } from './auth/jwt.js'
import { SigningKeyLoader } from './auth/registry.js'
import { credentialProvider } from './aws/credentials.js'
import { createPool, observeVersion } from './db/client.js'
import { createApp, type Lifecycle } from './http/app.js'
import type { Config } from './lib/config.js'
import { logger } from './lib/logging.js'
import { scheduleJittered } from './lib/schedule.js'
import { SnapshotManager } from './snapshot.js'
import { createFileStore } from './store/fileStore.js'
import { UsagePublisher } from './usage/publisher.js'
import { UsageRecorder } from './usage/recorder.js'

interface DrainableServer {
    close(cb: () => void): void
}

type ServeFn = (
    options: { fetch: Hono['fetch']; port: number; hostname: string },
    listeningListener: (info: { port: number }) => void
) => DrainableServer

/** Test seams. Production construction passes none of these. */
export interface IntegrationServerOverrides {
    pool?: Pool
    serve?: ServeFn
    exit?: (code: number) => void
}

const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms))

export class IntegrationServer {
    private readonly lifecycle: Lifecycle = { shuttingDown: false, ready: false }
    private pool: Pool | undefined
    private server: DrainableServer | undefined
    private recorder: UsageRecorder | undefined
    private cancelTimers: (() => void)[] = []
    private processListeners = new Map<string, (...args: unknown[]) => void>()
    private stopping = false

    constructor(
        private readonly config: Config,
        private readonly overrides: IntegrationServerOverrides = {}
    ) {}

    /** For probes and tests. The object is live; do not mutate it. */
    lifecycleState(): Lifecycle {
        return this.lifecycle
    }

    async start(): Promise<void> {
        const config = this.config

        if (this.overrides.pool) {
            this.pool = this.overrides.pool
        } else if (config.databaseUrl) {
            try {
                this.pool = await createPool(config.databaseUrl)
                logger.info('db:connected', {})
            } catch (err) {
                logger.error('db:connect_failed', { error: err instanceof Error ? err.message : String(err) })
                throw err
            }
        } else {
            // Guarded in loadConfig for production. Locally the service runs without usage
            // recording, which costs the rollup and nothing else.
            logger.warn('db:disabled', { reason: 'INTEGRATION_SERVICE_DATABASE_URL is unset, so no usage recording' })
        }
        const pool = this.pool

        const signingKeys = new SigningKeyLoader(config.secretsDir)
        try {
            await signingKeys.load()
        } catch (err) {
            logger.error('startup:signing_keys_load_failed', {
                dir: config.secretsDir,
                error: err instanceof Error ? err.message : String(err),
            })
            throw err
        }

        const store = createFileStore({
            dir: config.secretsDir,
            // Without Postgres there is no shared record of when content first appeared, so
            // the retirement verdict simply stays false rather than guessing.
            observeVersion: (hash) => (pool ? observeVersion(pool, hash) : Promise.resolve(null)),
        })

        const recorder = new UsageRecorder({ pool })
        this.recorder = recorder
        const snapshots = new SnapshotManager({ store, lifecycle: this.lifecycle, dir: config.secretsDir })

        const app = createApp({
            verifier: new JwtVerifier(signingKeys),
            lifecycle: this.lifecycle,
            resolveDeps: { loadSecrets: () => Promise.resolve(snapshots.current()), recorder },
            metricsToken: config.metricsToken,
        })

        await snapshots.reload()
        if (!this.lifecycle.ready) {
            logger.error('startup:no_credentials_on_mount', { dir: config.secretsDir })
        }

        const serveFn = this.overrides.serve ?? serve
        this.server = serveFn({ fetch: app.fetch, port: config.port, hostname: config.host }, (info) => {
            logger.info('server:started', { host: config.host, port: info.port, env: config.env })
        })

        this.cancelTimers.push(
            scheduleJittered(config.reloadSeconds * 1000, async () => {
                await snapshots.reload()
                await signingKeys.reload()
            }),
            scheduleJittered(config.usageFlushMs, () => recorder.flush()),
            scheduleJittered(24 * 60 * 60 * 1000, () => recorder.prune(config.retentionDays))
        )

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
            this.cancelTimers.push(scheduleJittered(config.usagePublishIntervalMs, () => publisher.publish()))
        }

        this.setupProcessListeners()
    }

    async stop(signal: string, error?: Error): Promise<void> {
        if (this.stopping) {
            return
        }
        this.stopping = true

        for (const [event, handler] of this.processListeners) {
            process.removeListener(event, handler)
        }
        this.processListeners.clear()

        logger.info('shutdown:start', { signal })
        this.lifecycle.shuttingDown = true
        for (const cancel of this.cancelTimers) {
            cancel()
        }

        const startedAt = Date.now()
        if (this.config.shutdownPrestopDelayMs > 0) {
            await sleep(this.config.shutdownPrestopDelayMs)
        }
        const drainBudget = Math.max(this.config.shutdownGraceMs - (Date.now() - startedAt), 1000)
        const server = this.server
        if (server) {
            await Promise.race([new Promise<void>((resolve) => server.close(() => resolve())), sleep(drainBudget)])
        }

        // Write what accumulated since the last flush, so a rolling restart does not lose
        // the reads that prove a caller has moved onto a new value.
        await this.recorder?.flush()
        if (this.pool) {
            await this.pool.end().catch((err: unknown) => {
                logger.error('shutdown:db_close_failed', {
                    error: err instanceof Error ? err.message : String(err),
                })
            })
        }
        logger.info('shutdown:complete', {})
        const exit = this.overrides.exit ?? process.exit
        exit(error ? 1 : 0)
    }

    private setupProcessListeners(): void {
        const on = (event: string, handler: (...args: unknown[]) => void): void => {
            this.processListeners.set(event, handler)
            process.on(event, handler)
        }
        on('SIGTERM', () => void this.stop('SIGTERM'))
        on('SIGINT', () => void this.stop('SIGINT'))
        on('unhandledRejection', (reason) => {
            logger.error('fatal:unhandled_rejection', { error: String(reason) })
            void this.stop('unhandledRejection', reason instanceof Error ? reason : new Error(String(reason)))
        })
        on('uncaughtException', (err) => {
            const error = err instanceof Error ? err : new Error(String(err))
            logger.error('fatal:uncaught_exception', { error: error.message })
            void this.stop('uncaughtException', error)
        })
    }
}
