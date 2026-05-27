import { randomUUID } from 'node:crypto'

import type { RedisLike } from './RedisCache'

const DEFAULT_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60 // 7 days — hard expiry
const DEFAULT_FRESH_SECONDS = 60 * 10 // 10 minutes — after this, trigger a refresh
const DEFAULT_LOCK_TTL_SECONDS = 60 // writer lock auto-expires
const DEFAULT_WAIT_INTERVAL_MS = 200
const DEFAULT_WAIT_TIMEOUT_MS = 10_000

export interface SharedBlobCacheOptions {
    cacheTtlSeconds?: number
    freshSeconds?: number
    lockTtlSeconds?: number
    waitIntervalMs?: number
    waitTimeoutMs?: number
}

export type BlobUpstream = () => Promise<Uint8Array>

/**
 * Redis-backed cache for an arbitrary binary blob, shared across instances.
 *
 * - Only the writer that wins the `SET NX EX` race fetches upstream and writes
 *   back the cache. Other concurrent callers either wait for the writer to
 *   publish (cold cache) or serve the previously cached value while a refresh
 *   runs in the background (stale-while-revalidate).
 * - Hard TTL keeps the cache available across long writer outages; a separate
 *   freshness timestamp triggers a background refresh after the soft window.
 *
 * Each blob lives under a caller-supplied namespace, so one Redis can host
 * many independent shared blobs (e.g. context-mill archive, future bundles)
 * without colliding.
 */
export class SharedBlobCache {
    private readonly cacheKey: string
    private readonly freshKey: string
    private readonly lockKey: string

    private cacheTtlSeconds: number
    private freshSeconds: number
    private lockTtlSeconds: number
    private waitIntervalMs: number
    private waitTimeoutMs: number

    constructor(
        private readonly redis: RedisLike,
        namespace: string,
        opts: SharedBlobCacheOptions = {}
    ) {
        const prefix = `mcp:shared-blob:${namespace}`
        this.cacheKey = `${prefix}:bytes`
        this.freshKey = `${prefix}:fresh`
        this.lockKey = `${prefix}:lock`

        this.cacheTtlSeconds = opts.cacheTtlSeconds ?? DEFAULT_CACHE_TTL_SECONDS
        this.freshSeconds = opts.freshSeconds ?? DEFAULT_FRESH_SECONDS
        this.lockTtlSeconds = opts.lockTtlSeconds ?? DEFAULT_LOCK_TTL_SECONDS
        this.waitIntervalMs = opts.waitIntervalMs ?? DEFAULT_WAIT_INTERVAL_MS
        this.waitTimeoutMs = opts.waitTimeoutMs ?? DEFAULT_WAIT_TIMEOUT_MS
    }

    /**
     * Return the cached blob bytes, fetching upstream via the single-writer
     * lock when the cache is cold or stale.
     */
    async fetch(upstream: BlobUpstream): Promise<Uint8Array> {
        const cached = await this.readCache()

        if (cached && cached.fresh) {
            return cached.bytes
        }

        if (cached) {
            // Stale-while-revalidate: serve what we have and try to refresh in
            // the background. The lock guarantees only one instance refreshes
            // even if many requests race here.
            void this.refreshInBackground(upstream)
            return cached.bytes
        }

        // Cold cache — race for the writer lock.
        const token = randomUUID()
        if (await this.acquireLock(token)) {
            try {
                const bytes = await upstream()
                await this.writeCache(bytes)
                return bytes
            } finally {
                await this.releaseLock(token)
            }
        }

        // Another writer holds the lock — wait for them to publish.
        const waited = await this.waitForCache()
        if (waited) {
            return waited
        }

        // Writer never published in time. Fetch ourselves without writing so
        // we don't trample whatever the lock holder eventually produces.
        return upstream()
    }

    private async readCache(): Promise<{ bytes: Uint8Array; fresh: boolean } | null> {
        const [raw, freshUntilStr] = await Promise.all([this.redis.get(this.cacheKey), this.redis.get(this.freshKey)])
        if (raw === null) {
            return null
        }
        const buf = Buffer.from(raw, 'base64')
        const bytes = new Uint8Array(buf.buffer, buf.byteOffset, buf.byteLength)
        const freshUntil = freshUntilStr !== null ? Number(freshUntilStr) : 0
        const fresh = Number.isFinite(freshUntil) && Date.now() < freshUntil
        return { bytes, fresh }
    }

    private async writeCache(bytes: Uint8Array): Promise<void> {
        const b64 = Buffer.from(bytes.buffer, bytes.byteOffset, bytes.byteLength).toString('base64')
        const freshUntil = Date.now() + this.freshSeconds * 1000
        await Promise.all([
            this.redis.set(this.cacheKey, b64, 'EX', this.cacheTtlSeconds),
            this.redis.set(this.freshKey, String(freshUntil), 'EX', this.cacheTtlSeconds),
        ])
    }

    private async acquireLock(token: string): Promise<boolean> {
        const result = await this.redis.set(this.lockKey, token, 'NX', 'EX', this.lockTtlSeconds)
        return result === 'OK'
    }

    private async releaseLock(_token: string): Promise<void> {
        // Best-effort. The lock TTL bounds the worst case (another writer's
        // entry being deleted on top); a Lua CAS could close that window but
        // would require widening the RedisLike interface.
        try {
            await this.redis.del(this.lockKey)
        } catch (err) {
            console.error(`[SharedBlobCache:${this.lockKey}] failed to release lock:`, err)
        }
    }

    private async waitForCache(): Promise<Uint8Array | null> {
        const start = Date.now()
        while (Date.now() - start < this.waitTimeoutMs) {
            await sleep(this.waitIntervalMs)
            const cached = await this.readCache()
            if (cached) {
                return cached.bytes
            }
        }
        return null
    }

    private async refreshInBackground(upstream: BlobUpstream): Promise<void> {
        const token = randomUUID()
        if (!(await this.acquireLock(token))) {
            return
        }
        try {
            const bytes = await upstream()
            await this.writeCache(bytes)
        } catch (err) {
            console.error(`[SharedBlobCache:${this.lockKey}] background refresh failed:`, err)
        } finally {
            await this.releaseLock(token)
        }
    }
}

function sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms))
}
