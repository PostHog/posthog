// Wires the service together and owns its lifecycle.
//
// Shutdown ordering is fixed: mark draining, wait out the prestop delay, drain the HTTP
// server, flush the usage recorder, end the pool. The flush sits after the drain so
// in-flight requests still record, and before the pool closes so it has somewhere to
// write. unhandledRejection and uncaughtException route through the same path, so a crash
// still flushes the reads that prove a caller has moved onto a new value.

import { serve } from '@hono/node-server'
import type { Hono } from 'hono'
import type { Pool } from 'pg'

import { JwtVerifier } from './auth/jwt'
import { SigningKeyLoader } from './auth/registry'
import { createPool, observeVersion } from './db/client'
import { createApp } from './http/app'
import type { Config } from './lib/config'
import { logger } from './lib/logging'
import { SecretMount } from './mount'
import type { Lifecycle } from './types'
import { UsageRecorder } from './usage/recorder'

/** How long a drain may take once the prestop window has passed. */
const DRAIN_TIMEOUT_MS = 10_000

const PRUNE_INTERVAL_MS = 24 * 60 * 60 * 1000

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

/**
 * Run `task` every `intervalMs`, starting after a delay drawn from [0, intervalMs) so
 * replicas do not reload in lockstep. The steady period is exactly `intervalMs` and the
 * first run lands inside it, because the reload is how a signing-key revocation reaches
 * this pod. Timers are unref'd so a pending one never holds the process open.
 */
export function everyJittered(intervalMs: number, task: () => Promise<void>): () => void {
    let repeat: NodeJS.Timeout | undefined
    const first = setTimeout(() => {
        void task()
        repeat = setInterval(() => void task(), intervalMs)
        repeat.unref()
    }, Math.random() * intervalMs)
    first.unref()
    return () => {
        clearTimeout(first)
        clearInterval(repeat)
    }
}

export class IntegrationServer {
    private readonly lifecycle: Lifecycle = { shuttingDown: false, ready: false }
    private pool: Pool | undefined
    private server: DrainableServer | undefined
    private recorder: UsageRecorder | undefined
    private mount: SecretMount | undefined
    private signingKeys: SigningKeyLoader | undefined
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

    /** Re-read the mount and the signing keys now, without waiting for the timer. */
    async reload(): Promise<void> {
        await this.mount?.reload()
        await this.signingKeys?.reload()
    }

    async start(): Promise<void> {
        const config = this.config

        if (this.overrides.pool) {
            this.pool = this.overrides.pool
        } else if (config.databaseUrl) {
            this.pool = await createPool(config.databaseUrl)
            logger.info('db:connected', {})
        } else {
            // Guarded in loadConfig for production. Locally the service runs without usage
            // recording, which costs the rollup and nothing else.
            logger.warn('db:disabled', { reason: 'INTEGRATION_SERVICE_DATABASE_URL is unset, so no usage recording' })
        }
        const pool = this.pool

        const signingKeys = new SigningKeyLoader(config.mountDir)
        this.signingKeys = signingKeys
        await signingKeys.load()

        const recorder = new UsageRecorder({ pool })
        this.recorder = recorder
        const mount = new SecretMount({
            dir: config.mountDir,
            lifecycle: this.lifecycle,
            // Without Postgres there is no shared record of when content first appeared, so
            // the retirement verdict simply stays false rather than guessing.
            observeVersion: (hash) => (pool ? observeVersion(pool, hash) : Promise.resolve(null)),
        })
        this.mount = mount

        const app = createApp({
            verifier: new JwtVerifier(signingKeys),
            lifecycle: this.lifecycle,
            credentials: () => mount.current(),
            recorder,
            metricsToken: config.metricsToken,
        })

        await mount.reload()
        if (!this.lifecycle.ready) {
            logger.error('startup:no_credentials_on_mount', { dir: config.mountDir })
        }

        const serveFn = this.overrides.serve ?? serve
        this.server = serveFn({ fetch: app.fetch, port: config.port, hostname: config.host }, (info) => {
            logger.info('server:started', { host: config.host, port: info.port, env: config.env })
        })

        this.cancelTimers.push(
            everyJittered(config.reloadSeconds * 1000, () => this.reload()),
            everyJittered(config.usageFlushMs, () => recorder.flush()),
            everyJittered(PRUNE_INTERVAL_MS, () => recorder.prune(config.retentionDays))
        )

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

        await sleep(this.config.shutdownPrestopDelayMs)
        const server = this.server
        if (server) {
            await Promise.race([new Promise<void>((resolve) => server.close(() => resolve())), sleep(DRAIN_TIMEOUT_MS)])
        }

        // Write what accumulated since the last flush, so a rolling restart does not lose
        // the reads that prove a caller has moved onto a new value.
        await this.recorder?.flush()
        if (this.pool) {
            await this.pool.end().catch((err: unknown) => {
                logger.error('shutdown:db_close_failed', { error: err instanceof Error ? err.message : String(err) })
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
