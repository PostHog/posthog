import { createHash } from 'node:crypto'
import { z } from 'zod'

import type { RedisLike } from './RedisCache'

const DEFAULT_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60 // 7 days — hard expiry
const DEFAULT_FRESH_SECONDS = 60 * 10 // 10 minutes — after this, trigger a refresh
const DEFAULT_LOCK_TTL_SECONDS = 60 // writer lock auto-expires
const DEFAULT_WAIT_INTERVAL_MS = 200
const DEFAULT_WAIT_TIMEOUT_MS = 10_000

const pointerSchema = z.object({
    sha: z.string().regex(/^[a-f0-9]{64}$/),
    etag: z.string().optional(),
    validatedAt: z.number().finite(),
})

// A delayed 304 must not replace a newer pointer or refresh metadata for an evicted blob.
const TOUCH_CACHE = `
if redis.call('GET', KEYS[1]) ~= ARGV[1] then return 0 end
if redis.call('EXPIRE', KEYS[2], ARGV[3]) == 0 then return 0 end
redis.call('SET', KEYS[1], ARGV[2], 'EX', ARGV[3])
return 1
`

const RELEASE_LOCK = `
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
`

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
 *   immutable bytes through a single current-version pointer.
 * - Hard TTL keeps the cache available across long writer outages; a separate
 *   freshness timestamp lets callers decide when to refresh after the soft
 *   window.
 *
 * Each blob lives under a caller-supplied namespace, so one Redis can host
 * many independent shared blobs (e.g. context-mill archive, future bundles)
 * without colliding.
 */
export interface SharedBlobRecord extends SharedBlobVersion {
    bytes: Uint8Array
}

export interface SharedBlobVersion extends z.infer<typeof pointerSchema> {
    fresh: boolean
    serialized: string
}

export class SharedBlobCache {
    public readonly currentKey: string
    public readonly lockKey: string
    private readonly blobKeyPrefix: string
    private validatedAt: number | undefined

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
        // Separate layouts let old and new processes coexist during a rolling deploy.
        const prefix = `mcp:shared-blob:${namespace}:v2`
        this.currentKey = `${prefix}:current`
        this.blobKeyPrefix = `${prefix}:blob`
        this.lockKey = `${prefix}:lock`

        this.cacheTtlSeconds = opts.cacheTtlSeconds ?? DEFAULT_CACHE_TTL_SECONDS
        this.freshSeconds = opts.freshSeconds ?? DEFAULT_FRESH_SECONDS
        this.lockTtlSeconds = opts.lockTtlSeconds ?? DEFAULT_LOCK_TTL_SECONDS
        this.waitIntervalMs = opts.waitIntervalMs ?? DEFAULT_WAIT_INTERVAL_MS
        this.waitTimeoutMs = opts.waitTimeoutMs ?? DEFAULT_WAIT_TIMEOUT_MS
    }

    getLastValidatedAt(): number | undefined {
        return this.validatedAt
    }

    protected blobKey(sha: string): string {
        return `${this.blobKeyPrefix}:${sha}`
    }

    protected async readCache(version?: SharedBlobVersion): Promise<SharedBlobRecord | null> {
        const pointer = version ?? (await this.readVersion())
        if (!pointer) {
            return null
        }
        const key = this.blobKey(pointer.sha)
        const raw = await this.redis.get(key)
        if (raw === null) {
            return null
        }
        const buf = Buffer.from(raw, 'base64')
        const bytes = new Uint8Array(buf.buffer, buf.byteOffset, buf.byteLength)
        if (hashBytes(bytes) !== pointer.sha) {
            // Remove only the corrupt content-addressed blob so a subsequent miss can repair it.
            await this.redis.del(key)
            throw new Error('Shared archive bytes do not match their content hash')
        }
        return { ...pointer, bytes }
    }

    /**
     * The small pointer is enough to check for updates without transferring archive bytes.
     */
    protected async readVersion(): Promise<SharedBlobVersion | null> {
        const serialized = await this.redis.get(this.currentKey)
        if (serialized === null) {
            return null
        }
        const pointer = pointerSchema.parse(JSON.parse(serialized))
        this.validatedAt = pointer.validatedAt
        return { ...pointer, fresh: Date.now() < pointer.validatedAt + this.freshSeconds * 1000, serialized }
    }

    protected async writeCache(bytes: Uint8Array, etag?: string): Promise<SharedBlobVersion> {
        const b64 = Buffer.from(bytes.buffer, bytes.byteOffset, bytes.byteLength).toString('base64')
        const pointer = { sha: hashBytes(bytes), etag, validatedAt: Date.now() }
        const serialized = JSON.stringify(pointer)
        // Publish immutable content first. A failed pointer write leaves the previous generation intact.
        await this.redis.set(this.blobKey(pointer.sha), b64, 'EX', this.cacheTtlSeconds)
        await this.redis.set(this.currentKey, serialized, 'EX', this.cacheTtlSeconds)
        this.validatedAt = pointer.validatedAt
        return { ...pointer, fresh: this.freshSeconds > 0, serialized }
    }

    /**
     * Refresh the validation timestamp and re-extend the hard TTLs without rewriting
     * the payload. Used when a conditional refresh confirms the cached bytes are
     * still current (HTTP 304), so the re-download and re-parse are skipped.
     */
    protected async touchCache(version: SharedBlobVersion): Promise<boolean> {
        const pointer = { sha: version.sha, etag: version.etag, validatedAt: Date.now() }
        const result = await this.redis.eval(
            TOUCH_CACHE,
            2,
            this.currentKey,
            this.blobKey(version.sha),
            version.serialized,
            JSON.stringify(pointer),
            this.cacheTtlSeconds
        )
        if (result === 1) {
            this.validatedAt = pointer.validatedAt
        }
        return result === 1
    }

    protected async acquireLock(token: string): Promise<boolean> {
        const result = await this.redis.set(this.lockKey, token, 'NX', 'EX', this.lockTtlSeconds)
        return result === 'OK'
    }

    protected async releaseLock(token: string): Promise<void> {
        try {
            await this.redis.eval(RELEASE_LOCK, 1, this.lockKey, token)
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

export function hashBytes(bytes: Uint8Array): string {
    return createHash('sha256').update(bytes).digest('hex')
}

function sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms))
}
