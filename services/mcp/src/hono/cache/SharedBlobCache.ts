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

/**
 * Redis-backed helpers for an arbitrary binary blob, shared across instances.
 *
 * - Callers can coordinate single-writer refreshes with the `SET NX EX` lock,
 *   wait for another writer to publish on cold cache misses, and read/write
 *   the shared bytes plus freshness marker.
 * - Hard TTL keeps the cache available across long writer outages; a separate
 *   freshness timestamp lets callers decide when to refresh after the soft
 *   window.
 *
 * Each blob lives under a caller-supplied namespace, so one Redis can host
 * many independent shared blobs (e.g. context-mill archive, future bundles)
 * without colliding.
 */
export interface SharedBlobRecord {
    bytes: Uint8Array
    fresh: boolean
    etag?: string
    /** Content hash written alongside the bytes, so readers can detect a change without reading them. */
    sha?: string
}

export interface SharedBlobVersion {
    sha: string
    fresh: boolean
    etag?: string
}

export class SharedBlobCache {
    public readonly cacheKey: string
    public readonly freshKey: string
    public readonly lockKey: string
    public readonly etagKey: string
    public readonly versionKey: string

    private cacheTtlSeconds: number
    private freshSeconds: number
    private lockTtlSeconds: number
    private waitIntervalMs: number
    private waitTimeoutMs: number

    constructor(
        protected readonly redis: RedisLike,
        namespace: string,
        opts: SharedBlobCacheOptions = {}
    ) {
        const prefix = `mcp:shared-blob:${namespace}`
        this.cacheKey = `${prefix}:bytes`
        this.freshKey = `${prefix}:fresh`
        this.lockKey = `${prefix}:lock`
        this.etagKey = `${prefix}:etag`
        this.versionKey = `${prefix}:sha`

        this.cacheTtlSeconds = opts.cacheTtlSeconds ?? DEFAULT_CACHE_TTL_SECONDS
        this.freshSeconds = opts.freshSeconds ?? DEFAULT_FRESH_SECONDS
        this.lockTtlSeconds = opts.lockTtlSeconds ?? DEFAULT_LOCK_TTL_SECONDS
        this.waitIntervalMs = opts.waitIntervalMs ?? DEFAULT_WAIT_INTERVAL_MS
        this.waitTimeoutMs = opts.waitTimeoutMs ?? DEFAULT_WAIT_TIMEOUT_MS
    }

    protected async readCache(): Promise<SharedBlobRecord | null> {
        const [raw, freshUntilStr, etag, sha] = await Promise.all([
            this.redis.get(this.cacheKey),
            this.redis.get(this.freshKey),
            this.redis.get(this.etagKey),
            this.redis.get(this.versionKey),
        ])
        if (raw === null) {
            return null
        }
        const buf = Buffer.from(raw, 'base64')
        const bytes = new Uint8Array(buf.buffer, buf.byteOffset, buf.byteLength)
        return { bytes, fresh: isFresh(freshUntilStr), etag: etag ?? undefined, sha: sha ?? undefined }
    }

    /**
     * The small keys only: enough to tell whether the shared bytes changed or went
     * stale, without transferring them. Null when no version was ever written,
     * which also covers entries written before the version key existed.
     */
    protected async readVersion(): Promise<SharedBlobVersion | null> {
        const [sha, freshUntilStr, etag] = await Promise.all([
            this.redis.get(this.versionKey),
            this.redis.get(this.freshKey),
            this.redis.get(this.etagKey),
        ])
        if (sha === null) {
            return null
        }
        return { sha, fresh: isFresh(freshUntilStr), etag: etag ?? undefined }
    }

    protected async writeCache(bytes: Uint8Array, validator?: string, sha?: string): Promise<void> {
        const b64 = Buffer.from(bytes.buffer, bytes.byteOffset, bytes.byteLength).toString('base64')
        const freshUntil = Date.now() + this.freshSeconds * 1000
        // Land the bytes before their validator, since the two live under separate
        // Redis keys with no cross-key transaction. If the validator write landed
        // first (or in parallel) and the bytes write then failed, Redis would keep
        // old bytes paired with the new validator — a stuck state where every later
        // conditional refresh sends the new validator, gets a 304, and touches the
        // stale bytes fresh again. Ordering it the other way makes both partial
        // failures self-heal: if the bytes write fails, the old bytes keep the old
        // validator (consistent); if only the validator write fails after new bytes
        // land, the next conditional refresh sends the old validator, gets a full
        // 200, and rewrites everything.
        await this.redis.set(this.cacheKey, b64, 'EX', this.cacheTtlSeconds)
        await Promise.all([
            this.redis.set(this.freshKey, String(freshUntil), 'EX', this.cacheTtlSeconds),
            // Keep the validator in lockstep with the bytes: store it when present,
            // clear any stale one otherwise so a later conditional request can't
            // send a validator that no longer matches the cached bytes.
            validator !== undefined
                ? this.redis.set(this.etagKey, validator, 'EX', this.cacheTtlSeconds)
                : this.redis.del(this.etagKey),
            // Same lockstep for the version: it lands last so a reader that sees a
            // new sha always finds the matching bytes already in place.
            sha !== undefined
                ? this.redis.set(this.versionKey, sha, 'EX', this.cacheTtlSeconds)
                : this.redis.del(this.versionKey),
        ])
    }

    /** Backfill the version key for a record that has bytes but no sha (written by an older layout). */
    protected async writeVersion(sha: string): Promise<void> {
        await this.redis.set(this.versionKey, sha, 'EX', this.cacheTtlSeconds)
    }

    /**
     * Refresh the freshness marker and re-extend the hard TTLs without rewriting
     * the payload. Used when a conditional refresh confirms the cached bytes are
     * still current (HTTP 304), so the re-download and re-parse are skipped.
     */
    protected async touchCache(): Promise<void> {
        const freshUntil = Date.now() + this.freshSeconds * 1000
        await Promise.all([
            this.redis.set(this.freshKey, String(freshUntil), 'EX', this.cacheTtlSeconds),
            this.redis.expire(this.cacheKey, this.cacheTtlSeconds),
            this.redis.expire(this.etagKey, this.cacheTtlSeconds),
            this.redis.expire(this.versionKey, this.cacheTtlSeconds),
        ])
    }

    protected async acquireLock(token: string): Promise<boolean> {
        const result = await this.redis.set(this.lockKey, token, 'NX', 'EX', this.lockTtlSeconds)
        return result === 'OK'
    }

    protected async releaseLock(_token: string): Promise<void> {
        // Best-effort. The lock TTL bounds the worst case (another writer's
        // entry being deleted on top); a Lua CAS could close that window but
        // would require widening the RedisLike interface.
        try {
            await this.redis.del(this.lockKey)
        } catch (err) {
            console.error(`[SharedBlobCache:${this.lockKey}] failed to release lock:`, err)
        }
    }

    protected async waitForCache(): Promise<Uint8Array | null> {
        const record = await this.waitForRecord()
        return record?.bytes ?? null
    }

    protected async waitForRecord(): Promise<SharedBlobRecord | null> {
        const start = Date.now()
        while (Date.now() - start < this.waitTimeoutMs) {
            await sleep(this.waitIntervalMs)
            const cached = await this.readCache()
            if (cached) {
                return cached
            }
        }
        return null
    }
}

function isFresh(freshUntilStr: string | null): boolean {
    const freshUntil = freshUntilStr !== null ? Number(freshUntilStr) : 0
    return Number.isFinite(freshUntil) && Date.now() < freshUntil
}

function sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms))
}
