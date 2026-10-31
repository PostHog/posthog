// Wires the service together and owns its lifecycle.
//
// Shutdown order is fixed: mark draining, wait out the prestop delay so Kubernetes has
// stopped routing here, drain the HTTP server, exit. unhandledRejection and
// uncaughtException take the same path rather than dropping in-flight requests.

import { serve } from '@hono/node-server'
import type { Hono } from 'hono'
import { createServer, type Server } from 'node:http'
import type { AddressInfo } from 'node:net'

import { JwtVerifier } from './auth/jwt'
import { SigningKeyLoader } from './auth/registry'
import { createApp } from './http/app'
import type { Config } from './lib/config'
import { logger } from './lib/logging'
import { register, shuttingDown } from './metrics'
import { SecretMount } from './mount'
import { createSecretSource, type SecretSnapshot, type SecretSource } from './source'
import type { Lifecycle } from './types'

/** How long a drain may take once the prestop window has passed. */
const DRAIN_TIMEOUT_MS = 10_000

interface DrainableServer {
    close(cb: () => void): void
}

type ServeFn = (
    options: { fetch: Hono['fetch']; port: number; hostname: string },
    listeningListener: (info: { port: number }) => void
) => DrainableServer

/** Test seams. Production construction passes none of these. */
export interface CredentialsServerOverrides {
    serve?: ServeFn
    exit?: (code: number) => void
    source?: SecretSource
}

const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms))

/** Run `task` every `intervalMs`. The timer is unref'd; the return value cancels it. */
export function every(intervalMs: number, task: () => Promise<void>): () => void {
    // A rejecting task would otherwise reach the unhandledRejection handler and exit the
    // process, so a blip in whatever the task talks to would take the pod down.
    const timer = setInterval(() => {
        task().catch((err: unknown) => {
            logger.error('timer:task_failed', { error: err instanceof Error ? err.message : String(err) })
        })
    }, intervalMs)
    timer.unref()
    return () => clearInterval(timer)
}

export class CredentialsServer {
    private readonly lifecycle: Lifecycle = { shuttingDown: false, ready: false }
    private server: DrainableServer | undefined
    private metricsServer: Server | undefined
    private source: SecretSource | undefined
    private mount: SecretMount | undefined
    private signingKeys: SigningKeyLoader | undefined
    private cancelTimers: (() => void)[] = []
    private processListeners = new Map<string, (...args: unknown[]) => void>()
    private stopping = false

    constructor(
        private readonly config: Config,
        private readonly overrides: CredentialsServerOverrides = {}
    ) {}

    /** For probes and tests. The object is live; do not mutate it. */
    lifecycleState(): Lifecycle {
        return this.lifecycle
    }

    /** The port the metrics listener bound, once start() has run. */
    metricsPort(): number | undefined {
        const address = this.metricsServer?.address()
        return address && typeof address === 'object' ? (address as AddressInfo).port : undefined
    }

    /** Re-read the secret now, without waiting for the timer. */
    async reload(): Promise<void> {
        const source = this.source
        if (source) {
            this.apply(source, await source.read())
        }
    }

    /** Apply one snapshot of the secret to the signing keys and the secrets together. */
    private apply(source: SecretSource, snapshot: SecretSnapshot | null): void {
        // Keys before secrets: a revocation and a rotation can land in one secret
        // edit, and the revoked caller must not see the new values in the gap between.
        this.signingKeys?.reloadFrom(snapshot?.values ?? null)
        this.applySecrets(source, snapshot)
    }

    private applySecrets(source: SecretSource, snapshot: SecretSnapshot | null): void {
        const mount = this.mount
        if (!mount) {
            return
        }
        const before = mount.current()?.versionId
        mount.apply(snapshot?.values ?? null)
        const after = mount.current()
        if (after && after.versionId !== before) {
            logger.info('secrets:applied', {
                source: source.kind,
                versionId: after.versionId,
                revision: snapshot?.revision ?? null,
            })
        }
        this.lifecycle.ready = after != null && this.signingKeys?.isLoaded === true
    }

    async start(): Promise<void> {
        const config = this.config

        const source = this.overrides.source ?? createSecretSource(config)
        this.source = source
        const signingKeys = new SigningKeyLoader(source.description)
        this.signingKeys = signingKeys
        const mount = new SecretMount({})
        this.mount = mount

        const first = await source.read()
        // Boot fails closed when the secret carries no usable signing keys. A Kubernetes API
        // that cannot be read at boot is different: the pod stays not-ready, and the watch
        // retries until the first read succeeds, the same as an empty mount.
        if (first || source.kind === 'directory') {
            signingKeys.loadFrom(first?.values ?? {})
        }
        this.applySecrets(source, first)

        const app = createApp({
            verifier: new JwtVerifier(signingKeys),
            lifecycle: this.lifecycle,
            secrets: () => mount.current(),
        })

        if (!this.lifecycle.ready) {
            logger.error('startup:no_secrets_on_mount', { source: source.description })
        }

        source.watch((snapshot) => this.apply(source, snapshot))
        this.cancelTimers.push(() => source.stop())

        const serveFn = this.overrides.serve ?? serve
        this.server = serveFn({ fetch: app.fetch, port: config.port, hostname: config.host }, (info) => {
            logger.info('server:started', { host: config.host, port: info.port, env: config.env })
        })

        // Its own listener, never the serving port: the chart exposes only `port`, so the
        // scrape stays in-cluster the same way every other service's does.
        this.metricsServer = createServer((req, res) => {
            if (req.url !== '/metrics') {
                res.statusCode = 404
                res.end()
                return
            }
            shuttingDown.set(this.lifecycle.shuttingDown ? 1 : 0)
            register.metrics().then(
                (body) => {
                    res.setHeader('Content-Type', register.contentType)
                    res.end(body)
                },
                () => {
                    res.statusCode = 500
                    res.end()
                }
            )
        })
        this.metricsServer.listen(config.metricsPort, config.host)

        this.cancelTimers.push(every(config.reloadSeconds * 1000, () => this.reload()))

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
        this.metricsServer?.close()

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
