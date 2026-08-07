// Three-tier read path for the credential snapshot: in-process, then envelope-encrypted
// Redis, then the backing secret store. One secret means one snapshot, so this holds a
// single entry rather than a map.
//
// Availability shapes this more than performance does. Callers do not cache, so every
// credential read reaches this service, and a Secrets Manager blip must degrade rather
// than fail: an expired snapshot is still served (last known good) while
// integration_secret_serving_stale_seconds climbs. Failing closed on a refresh failure
// would turn a transient AWS wobble into a fleet-wide sync outage.
//
// Redis holds only sealed bytes (see envelope.ts). A decrypt failure is treated as a miss,
// not an error, so a poisoned or stale-format entry costs one extra store read instead of
// breaking the request.

import type { Redis } from 'ioredis'

import { logger } from '../lib/logging.js'
import { cacheHitsTotal, secretAgeSeconds, servingStaleSeconds, storeErrorsTotal } from '../metrics.js'
import type { SecretStore } from '../store/types.js'
import type { SecretsSnapshot } from '../types.js'
import type { EnvelopeCipher } from './envelope.js'

interface Entry {
    snapshot: SecretsSnapshot
    expiresAt: number
}

export interface SecretCacheOptions {
    store: SecretStore
    cipher: EnvelopeCipher
    /** Optional: the service runs without an L2 when no Redis URL is configured (local dev). */
    redis?: Redis | undefined
    env: string
    ttlSeconds: number
    now?: () => number
}

/** Redis key. Versioned so an envelope format change is a cold start, not a decrypt storm. */
function redisKeyFor(env: string): string {
    return `integration-service:v1:${env}:secrets`
}

export class SecretCache {
    private readonly store: SecretStore
    private readonly cipher: EnvelopeCipher
    private readonly redis: Redis | undefined
    private readonly env: string
    private readonly ttlMs: number
    private readonly now: () => number

    private entry: Entry | null = null
    private inFlight: Promise<SecretsSnapshot | null> | null = null
    // L2 writes are fire-and-forget so a cold read never waits on the cache it is
    // populating. Tracked anyway so shutdown and tests can wait for them to drain instead
    // of depending on microtask timing.
    private readonly pendingWrites = new Set<Promise<void>>()

    constructor(opts: SecretCacheOptions) {
        this.store = opts.store
        this.cipher = opts.cipher
        this.redis = opts.redis
        this.env = opts.env
        this.ttlMs = opts.ttlSeconds * 1000
        this.now = opts.now ?? Date.now
    }

    async get(): Promise<SecretsSnapshot | null> {
        if (this.entry && this.entry.expiresAt > this.now()) {
            cacheHitsTotal.labels({ layer: 'l1' }).inc()
            return this.entry.snapshot
        }

        // Single-flight: a burst of concurrent requests must not each hit Redis and
        // Secrets Manager.
        if (this.inFlight) {
            return this.inFlight
        }
        const load = this.refresh().finally(() => {
            this.inFlight = null
        })
        this.inFlight = load
        return load
    }

    private async refresh(): Promise<SecretsSnapshot | null> {
        const fromRedis = await this.readRedis()
        if (fromRedis) {
            cacheHitsTotal.labels({ layer: 'l2' }).inc()
            this.remember(fromRedis)
            return fromRedis
        }

        try {
            const snapshot = await this.store.load()
            cacheHitsTotal.labels({ layer: 'store' }).inc()
            if (!snapshot) {
                return null
            }
            this.remember(snapshot)
            this.trackWrite(this.writeRedis(snapshot))
            servingStaleSeconds.set(0)
            if (snapshot.versionCreatedAt) {
                secretAgeSeconds.set((this.now() - Date.parse(snapshot.versionCreatedAt)) / 1000)
            }
            return snapshot
        } catch (err) {
            storeErrorsTotal.inc()
            // Last known good. An expired snapshot is far better than failing every
            // credential read, and the staleness gauge is what makes it visible.
            if (this.entry) {
                const staleFor = (this.now() - Date.parse(this.entry.snapshot.fetchedAt)) / 1000
                servingStaleSeconds.set(staleFor)
                logger.warn('cache:serving_stale', {
                    staleForSeconds: Math.round(staleFor),
                    error: err instanceof Error ? err.message : String(err),
                })
                return this.entry.snapshot
            }
            logger.error('cache:load_failed', { error: err instanceof Error ? err.message : String(err) })
            throw err
        }
    }

    private remember(snapshot: SecretsSnapshot): void {
        this.entry = { snapshot, expiresAt: this.now() + this.ttlMs }
    }

    private trackWrite(write: Promise<void>): void {
        this.pendingWrites.add(write)
        void write.finally(() => this.pendingWrites.delete(write))
    }

    /** Wait for in-flight L2 writes to drain. Used on shutdown and in tests. */
    async settled(): Promise<void> {
        await Promise.all(this.pendingWrites)
    }

    private async readRedis(): Promise<SecretsSnapshot | null> {
        if (!this.redis) {
            return null
        }
        const key = redisKeyFor(this.env)
        try {
            const sealed = await this.redis.get(key)
            if (!sealed) {
                return null
            }
            return JSON.parse(await this.cipher.open(sealed, key)) as SecretsSnapshot
        } catch (err) {
            // Covers both a Redis outage and an unopenable entry. Either way the store
            // read below is the correct fallback.
            logger.warn('cache:l2_read_failed', { error: err instanceof Error ? err.message : String(err) })
            return null
        }
    }

    private async writeRedis(snapshot: SecretsSnapshot): Promise<void> {
        if (!this.redis) {
            return
        }
        const key = redisKeyFor(this.env)
        try {
            const sealed = await this.cipher.seal(JSON.stringify(snapshot), key)
            await this.redis.set(key, sealed, 'EX', Math.ceil(this.ttlMs / 1000))
        } catch (err) {
            // A failed cache write costs latency on the next read, nothing more.
            logger.warn('cache:l2_write_failed', { error: err instanceof Error ? err.message : String(err) })
        }
    }

    /**
     * Load the snapshot once at boot, before readiness flips, so the first real request
     * never pays a cold read and a misconfigured store is caught by the readiness probe
     * rather than by a caller.
     */
    async warm(): Promise<void> {
        try {
            await this.get()
        } catch (err) {
            logger.warn('cache:warm_failed', { error: err instanceof Error ? err.message : String(err) })
        }
    }
}
