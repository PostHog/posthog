import { createHash, randomUUID } from 'node:crypto'

import { fetchAndExtractEntries } from '@/resources/internals'
import type { ContextMillResource } from '@/resources/manifest-types'

import { contextMillBodyReadsTotal, contextMillCacheEventsTotal } from '../metrics'
import type { RedisLike } from './RedisCache'
import { SharedBlobCache, type SharedBlobCacheOptions } from './SharedBlobCache'

const NAMESPACE = 'context-mill'
const BODY_KEY_PREFIX = `mcp:shared-blob:${NAMESPACE}:body`
const DEFAULT_BODY_TTL_SECONDS = 7 * 24 * 60 * 60
const BODY_SIZE_WARN_BYTES = 256 * 1024

export interface SlimManifestEntry {
    uri: string
    name: string
    mimeType: string
    description: string
}

export interface SlimManifest {
    entries: SlimManifestEntry[]
}

export interface ResourceBody {
    mimeType: string
    text: string
}

export interface ContextMillResourceCacheOptions extends SharedBlobCacheOptions {
    bodyTtlSeconds?: number
    localUrl?: string
}

export type ContextMillCacheResult = 'fresh_hit' | 'stale_hit' | 'cold_refresh' | 'waited' | 'fallback'

export interface ContextMillLoadResult {
    manifest: SlimManifest
    result: ContextMillCacheResult
}

/**
 * Redis-backed cache for the context-mill resource bundle.
 *
 * Splits storage into two layers:
 *
 * - A small slim manifest blob (handled by the base `SharedBlobCache`) that
 *   carries `{ entries: [{ uri, name, mimeType, description }] }` — used by
 *   `resources/list` and warmup. Cheap to fetch on every cold pod.
 * - One body key per resource (`mcp:shared-blob:context-mill:body:<sha256(uri)>`)
 *   that carries the heavy `{ mimeType, text }` payload — fetched lazily only
 *   when `resources/read` resolves a URI.
 *
 * Bodies are URI-addressed (no per-publish generation token) so the latest
 * publish always overwrites the same key. The instant a writer pod finishes
 * `writeBodies`, every other pod reading by URI sees the new content — no
 * waiting for individual pods to refresh their in-memory manifest.
 *
 * Resources removed upstream are NOT explicitly deleted: their bodies just
 * stop getting their TTL refreshed and age out naturally. This gives clients
 * holding stale URIs graceful access to the previous content until the body
 * fully expires.
 */
export class ContextMillResourceCache extends SharedBlobCache {
    private readonly bodyTtlSeconds: number
    private readonly localUrl: string | undefined

    constructor(redis: RedisLike, opts: ContextMillResourceCacheOptions = {}) {
        super(redis, `${NAMESPACE}:manifest`, opts)
        this.localUrl = opts.localUrl
        this.bodyTtlSeconds = opts.bodyTtlSeconds ?? DEFAULT_BODY_TTL_SECONDS
    }

    /**
     * Returns the slim manifest. Cold/stale paths load entries inside the
     * SharedBlobCache writer lock, publish every body key, and only then write
     * back the slim manifest.
     */
    async loadOrRefresh(): Promise<ContextMillLoadResult> {
        const { bytes, result } = await this.fetch()
        return {
            manifest: JSON.parse(new TextDecoder().decode(bytes)) as SlimManifest,
            result,
        }
    }

    private async fetch(): Promise<{ bytes: Uint8Array; result: ContextMillCacheResult }> {
        const cached = await this.readCache()

        if (cached && cached.fresh) {
            contextMillCacheEventsTotal.inc({ event: 'fresh_hit' })
            return { bytes: cached.bytes, result: 'fresh_hit' }
        }

        if (cached) {
            // Stale-while-revalidate: serve what we have and try to refresh in
            // the background. The lock guarantees only one instance refreshes
            // even if many requests race here.
            contextMillCacheEventsTotal.inc({ event: 'stale_hit' })
            void this.refreshInBackground()
            return { bytes: cached.bytes, result: 'stale_hit' }
        }

        // Cold cache — race for the writer lock.
        contextMillCacheEventsTotal.inc({ event: 'cold_miss' })
        const token = randomUUID()
        if (await this.acquireLock(token)) {
            contextMillCacheEventsTotal.inc({ event: 'lock_acquired' })
            try {
                const bytes = await this.loadBlob()
                await this.writeCache(bytes)
                return { bytes, result: 'cold_refresh' }
            } finally {
                await this.releaseLock(token)
            }
        }

        // Another writer holds the lock — wait for them to publish.
        contextMillCacheEventsTotal.inc({ event: 'lock_contended' })
        const waited = await this.waitForCache()
        if (waited) {
            contextMillCacheEventsTotal.inc({ event: 'wait_success' })
            return { bytes: waited, result: 'waited' }
        }

        // Writer never published in time. Fetch ourselves without writing so
        // we don't trample whatever the lock holder eventually produces.
        contextMillCacheEventsTotal.inc({ event: 'wait_timeout' })
        return { bytes: await this.loadBlob(), result: 'fallback' }
    }

    private async loadBlob(): Promise<Uint8Array> {
        const entries = await this.loadEntries()
        await this.writeBodies(entries)
        const slim: SlimManifest = {
            entries: entries.map((e) => ({
                uri: e.uri,
                name: e.name,
                mimeType: e.resource.mimeType,
                description: e.resource.description,
            })),
        }
        return new TextEncoder().encode(JSON.stringify(slim))
    }

    protected async loadEntries(): Promise<ContextMillResource[]> {
        return fetchAndExtractEntries(this.localUrl)
    }

    private async refreshInBackground(): Promise<void> {
        const token = randomUUID()
        if (!(await this.acquireLock(token))) {
            contextMillCacheEventsTotal.inc({ event: 'lock_contended' })
            return
        }
        contextMillCacheEventsTotal.inc({ event: 'lock_acquired' })
        try {
            const bytes = await this.loadBlob()
            await this.writeCache(bytes)
            contextMillCacheEventsTotal.inc({ event: 'background_success' })
        } catch (err) {
            contextMillCacheEventsTotal.inc({ event: 'background_error' })
            console.error(`[ContextMillResourceCache:${this.lockKey}] background refresh failed:`, err)
        } finally {
            await this.releaseLock(token)
        }
    }

    /**
     * Invalidate the slim manifest so the next `loadOrRefresh` is treated as
     * cold and fetches upstream. Use from miss-recovery paths — e.g. when a
     * body lookup returns null because Redis evicted it but the manifest is
     * still fresh, plain `loadOrRefresh` would short-circuit.
     */
    async invalidate(): Promise<void> {
        await Promise.all([this.redis.del(this.cacheKey), this.redis.del(this.freshKey)])
    }

    /**
     * Returns the body for `uri` if present in Redis. Returns null only when
     * the body has aged out (TTL elapsed without a republish) or was evicted
     * under memory pressure. Callers should treat null as "trigger refresh
     * and degrade the current request to empty contents."
     */
    async readBody(uri: string): Promise<ResourceBody | null> {
        const raw = await this.redis.get(bodyKey(uri))
        if (raw === null) {
            contextMillBodyReadsTotal.inc({ status: 'miss' })
            return null
        }
        try {
            const body = JSON.parse(raw) as ResourceBody
            contextMillBodyReadsTotal.inc({ status: 'hit' })
            return body
        } catch (err) {
            contextMillBodyReadsTotal.inc({ status: 'parse_error' })
            throw err
        }
    }

    private async writeBodies(entries: readonly ContextMillResource[]): Promise<void> {
        await Promise.all(
            entries.map(async (entry) => {
                const stored: ResourceBody = {
                    mimeType: entry.resource.mimeType,
                    text: entry.resource.text,
                }
                const serialized = JSON.stringify(stored)
                if (serialized.length > BODY_SIZE_WARN_BYTES) {
                    console.warn(
                        `[ContextMillResourceCache] body for "${entry.uri}" is ${serialized.length} bytes — approaching Redis bulk-len limits`
                    )
                }
                await this.redis.set(bodyKey(entry.uri), serialized, 'EX', this.bodyTtlSeconds)
            })
        )
    }
}

function bodyKey(uri: string): string {
    return `${BODY_KEY_PREFIX}:${sha256(uri)}`
}

function sha256(input: string): string {
    return createHash('sha256').update(input).digest('hex')
}
