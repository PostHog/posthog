/**
 * `createIngress` — the public factory for wiring up an `agent-ingress`
 * instance. Used by both the runnable bin (`./index.ts`) and the e2e test
 * harness (`services/agent-tests`) so the two paths stay in lockstep.
 *
 * The factory constructs anything you don't override from env defaults
 * (`loadConfig()`), wires up the Express app, and returns a handle with
 * `start(port?)` / `stop()`. It does NOT call `listen()` until you ask it
 * to — both bins and tests want explicit control of when the port opens.
 *
 * Ownership-aware shutdown: `stop()` only disposes the deps the factory
 * constructed itself. If you pass in a shared `queue` / `bus` / `posthogDb`
 * (as the harness does so ingress and runner can talk in-process), you stay
 * responsible for disconnecting them.
 */
import type { AddressInfo } from 'node:net'
import type { Express } from 'ultimate-express'

import {
    ApplicationsRepository,
    EncryptedFields,
    IdentitiesRepository,
    InMemorySessionBus,
    PosthogDbClient,
    RedisSessionBus,
    SessionBus,
    SessionQueueManager,
    logger,
} from '@posthog/agent-core'

import { loadConfig, type IngressConfig } from './config'
import { RevisionResolver } from './resolver'
import { buildServer, type ServerDeps } from './server'

export interface IngressOverrides {
    /* === Config / behaviour === */
    /** Defaults: env-derived via `loadConfig()`. Anything missing falls back to dev defaults. */
    config?: Partial<IngressConfig>

    /* === Shared deps (provide to share across ingress + runner in tests) === */
    queue?: SessionQueueManager
    bus?: SessionBus
    posthogDb?: PosthogDbClient
    repository?: ApplicationsRepository
    identities?: IdentitiesRepository

    /* === ServerDeps behaviour overrides === */
    /** Override the per-request PAT verifier. Default uses `ApplicationsRepository.verifyTokenIdentity`. */
    authenticatePat?: ServerDeps['authenticatePat']
    /** Override the posthog-internal verifier. Default is "no callback, 500 on use" — supply for tests. */
    verifyPostHogInternal?: ServerDeps['verifyPostHogInternal']
    /** Override the secret resolver. Default reads from the agent application's encrypted_env. */
    loadSecret?: ServerDeps['loadSecret']
    /** Override the identity resolver. Default uses `IdentitiesRepository.resolveIdentity`. */
    resolveIdentity?: ServerDeps['resolveIdentity']
    /**
     * Queue name to enqueue sessions onto. Default `default`. Tests
     * override this for isolation from a co-running prod-shape runner.
     */
    queueName?: string
}

export interface Ingress {
    /** The Express app. Exposed for supertest and inspection. */
    readonly app: Express
    /** Full `ServerDeps` passed to `buildServer`. Useful for assertions. */
    readonly deps: ServerDeps
    /** Listen on the given port (default: from config). Resolves with the bound port. */
    start(port?: number): Promise<{ port: number }>
    /** Dispose deps the factory created itself; leaves shared deps alone. Idempotent. */
    stop(): Promise<void>
}

export { buildServer, type ServerDeps } from './server'
export { RevisionResolver } from './resolver'

export async function createIngress(overrides: IngressOverrides = {}): Promise<Ingress> {
    const config = { ...loadConfig(), ...overrides.config }

    // Track what the factory constructed so `stop()` can clean it up
    // without touching deps the caller supplied.
    const owned: Array<() => Promise<void>> = []

    const posthogDb =
        overrides.posthogDb ??
        (() => {
            const db = new PosthogDbClient({ dbUrl: config.posthogDbUrl })
            owned.push(() => db.disconnect())
            return db
        })()

    const encryption = new EncryptedFields(config.encryptionSaltKeys)

    const repository = overrides.repository ?? new ApplicationsRepository({ db: posthogDb, encryption })
    const identities = overrides.identities ?? new IdentitiesRepository({ db: posthogDb })

    const queue =
        overrides.queue ??
        (await (async () => {
            const q = new SessionQueueManager({ pool: { dbUrl: config.queueDbUrl } })
            await q.connect()
            owned.push(() => q.disconnect())
            return q
        })())

    const bus = overrides.bus ?? createDefaultBus(config)
    if (!overrides.bus) {
        owned.push(() => bus.disconnect())
    }

    const resolver = new RevisionResolver({
        repository,
        ttlMs: config.resolverTtlMs,
        domainSuffix: config.domainSuffix,
    })

    const deps: ServerDeps = {
        queue,
        bus,
        resolver,
        repository,
        identities,
        domainSuffix: config.domainSuffix,
        routingMode: config.routingMode,
        authenticatePat: overrides.authenticatePat,
        verifyPostHogInternal: overrides.verifyPostHogInternal,
        loadSecret: overrides.loadSecret,
        resolveIdentity: overrides.resolveIdentity,
        queueName: overrides.queueName,
    }
    const app = buildServer(deps)

    let started = false
    return {
        app,
        deps,
        async start(port = config.port): Promise<{ port: number }> {
            if (started) {
                throw new Error('createIngress: start() called twice')
            }
            started = true
            return new Promise((resolve, reject) => {
                try {
                    app.listen(port, () => {
                        const addr = (app as unknown as { address(): AddressInfo }).address()
                        resolve({ port: addr.port })
                    })
                } catch (err) {
                    reject(err)
                }
            })
        },
        async stop(): Promise<void> {
            // ultimate-express has no app-level close; the process exit
            // releases the port. Just unwind owned deps in reverse order.
            for (const dispose of owned.reverse()) {
                try {
                    await dispose()
                } catch (err) {
                    logger.warn({ err }, 'createIngress: dispose threw')
                }
            }
            owned.length = 0
        },
    }
}

function createDefaultBus(config: IngressConfig): SessionBus {
    if (config.redisUrl) {
        return new RedisSessionBus({ url: config.redisUrl })
    }
    logger.warn('REDIS_URL not set; using in-memory bus (single-process only — not safe for production)')
    return new InMemorySessionBus()
}
