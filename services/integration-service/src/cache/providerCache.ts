// Three-tier read path for provider snapshots: in-process map, then envelope-encrypted
// Redis, then the backing secret store.
//
// Availability shapes this more than performance does. Warehouse syncs and OAuth
// refreshes now depend on this service, so a Secrets Manager blip must degrade rather
// than fail: an expired entry is still served (last-known-good) while
// integration_secret_serving_stale_seconds climbs, and only a cold miss with a broken
// store surfaces an error. The alternative — failing closed on refresh failure — would
// turn a transient AWS wobble into a fleet-wide sync outage.
//
// Redis holds only sealed bytes (see envelope.ts). A decrypt failure is treated as a
// miss, not an error, so a poisoned or stale-format entry costs one extra store read
// instead of breaking the request.

import type { Redis } from 'ioredis'

import { logger } from '../lib/logging.js'
import { cacheHitsTotal, secretAgeSeconds, servingStaleSeconds, storeErrorsTotal } from '../metrics.js'
import type { SecretStore } from '../store/types.js'
import type { ProviderSnapshot } from '../types.js'
import type { EnvelopeCipher } from './envelope.js'

interface Entry {
    snapshot: ProviderSnapshot
    expiresAt: number
}

export interface ProviderCacheOptions {
    store: SecretStore
    cipher: EnvelopeCipher
    /** Optional: the service runs without an L2 when no Redis URL is configured (local dev). */
    redis?: Redis | undefined
    env: string
    ttlSeconds: number
    now?: () => number
}

/** Redis key. Versioned so an envelope format change is a cold start, not a decrypt storm. */
function redisKeyFor(env: string, provider: string): string {
    return `integration-service:v1:${env}:provider:${provider}`
}

export class ProviderCache {
    private readonly store: SecretStore
    private readonly cipher: EnvelopeCipher
    private readonly redis: Redis | undefined
    private readonly env: string
    private readonly ttlMs: number
    private readonly now: () => number

    private readonly entries = new Map<string, Entry>()
    private readonly inFlight = new Map<string, Promise<ProviderSnapshot | null>>()
    // L2 writes are fire-and-forget so a cold read never waits on the cache it is
    // populating. Tracked anyway so shutdown and tests can wait for them to drain
    // instead of depending on microtask timing.
    private readonly pendingWrites = new Set<Promise<void>>()

    constructor(opts: ProviderCacheOptions) {
        this.store = opts.store
        this.cipher = opts.cipher
        this.redis = opts.redis
        this.env = opts.env
        this.ttlMs = opts.ttlSeconds * 1000
        this.now = opts.now ?? Date.now
    }

    async get(provider: string): Promise<ProviderSnapshot | null> {
        const entry = this.entries.get(provider)
        if (entry && entry.expiresAt > this.now()) {
            cacheHitsTotal.labels({ layer: 'l1' }).inc()
            return entry.snapshot
        }

        // Single-flight per provider: a burst of concurrent requests for the same
        // provider must not each hit Redis and Secrets Manager.
        const existing = this.inFlight.get(provider)
        if (existing) {
            return existing
        }

        const load = this.refresh(provider).finally(() => this.inFlight.delete(provider))
        this.inFlight.set(provider, load)
        return load
    }

    private async refresh(provider: string): Promise<ProviderSnapshot | null> {
        const fromRedis = await this.readRedis(provider)
        if (fromRedis) {
            cacheHitsTotal.labels({ layer: 'l2' }).inc()
            this.remember(provider, fromRedis)
            return fromRedis
        }

        try {
            const snapshot = await this.store.loadProvider(provider)
            cacheHitsTotal.labels({ layer: 'store' }).inc()
            if (!snapshot) {
                return null
            }
            this.remember(provider, snapshot)
            this.trackWrite(this.writeRedis(provider, snapshot))
            servingStaleSeconds.labels({ provider }).set(0)
            if (snapshot.currentActivatedAt) {
                const ageSeconds = (this.now() - Date.parse(snapshot.currentActivatedAt)) / 1000
                secretAgeSeconds.labels({ provider }).set(ageSeconds)
            }
            return snapshot
        } catch (err) {
            storeErrorsTotal.labels({ provider }).inc()
            // Last-known-good. An expired entry is far better than failing a sync, and
            // the staleness gauge is what makes the degradation visible.
            const stale = this.entries.get(provider)
            if (stale) {
                const staleFor = (this.now() - Date.parse(stale.snapshot.fetchedAt)) / 1000
                servingStaleSeconds.labels({ provider }).set(staleFor)
                logger.warn('cache:serving_stale', {
                    provider,
                    staleForSeconds: Math.round(staleFor),
                    error: err instanceof Error ? err.message : String(err),
                })
                return stale.snapshot
            }
            logger.error('cache:load_failed', {
                provider,
                error: err instanceof Error ? err.message : String(err),
            })
            throw err
        }
    }

    private remember(provider: string, snapshot: ProviderSnapshot): void {
        this.entries.set(provider, { snapshot, expiresAt: this.now() + this.ttlMs })
    }

    private trackWrite(write: Promise<void>): void {
        this.pendingWrites.add(write)
        void write.finally(() => this.pendingWrites.delete(write))
    }

    /** Wait for in-flight L2 writes to drain. Used on shutdown and in tests. */
    async settled(): Promise<void> {
        await Promise.all([...this.pendingWrites])
    }

    private async readRedis(provider: string): Promise<ProviderSnapshot | null> {
        if (!this.redis) {
            return null
        }
        const key = redisKeyFor(this.env, provider)
        try {
            const sealed = await this.redis.get(key)
            if (!sealed) {
                return null
            }
            return JSON.parse(await this.cipher.open(sealed, key)) as ProviderSnapshot
        } catch (err) {
            // Covers both a Redis outage and an unopenable entry. Either way the store
            // read below is the correct fallback.
            logger.warn('cache:l2_read_failed', {
                provider,
                error: err instanceof Error ? err.message : String(err),
            })
            return null
        }
    }

    private async writeRedis(provider: string, snapshot: ProviderSnapshot): Promise<void> {
        if (!this.redis) {
            return
        }
        const key = redisKeyFor(this.env, provider)
        try {
            const sealed = await this.cipher.seal(JSON.stringify(snapshot), key)
            await this.redis.set(key, sealed, 'EX', Math.ceil(this.ttlMs / 1000))
        } catch (err) {
            // A failed cache write costs latency on the next read, nothing more.
            logger.warn('cache:l2_write_failed', {
                provider,
                error: err instanceof Error ? err.message : String(err),
            })
        }
    }

    /**
     * Warm every provider. Called at boot before readiness flips, so the first real
     * request never pays a cold Secrets Manager read, and a misconfigured store is
     * caught by the readiness probe rather than by a caller.
     */
    async warm(providers: readonly string[]): Promise<void> {
        await Promise.all(
            providers.map(async (provider) => {
                try {
                    await this.get(provider)
                } catch (err) {
                    logger.warn('cache:warm_failed', {
                        provider,
                        error: err instanceof Error ? err.message : String(err),
                    })
                }
            })
        )
    }
}
