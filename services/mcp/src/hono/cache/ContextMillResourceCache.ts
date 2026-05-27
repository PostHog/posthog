import { createHash } from 'node:crypto'

import type { ContextMillResource } from '@/resources/manifest-types'

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
}

/**
 * Redis-backed cache for the context-mill resource bundle.
 *
 * Splits storage into two layers:
 *
 * - A small slim manifest blob (handled by the inner `SharedBlobCache`) that
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
export class ContextMillResourceCache {
    private readonly manifestCache: SharedBlobCache
    private readonly bodyTtlSeconds: number

    constructor(
        private readonly redis: RedisLike,
        opts: ContextMillResourceCacheOptions = {}
    ) {
        this.manifestCache = new SharedBlobCache(redis, `${NAMESPACE}:manifest`, opts)
        this.bodyTtlSeconds = opts.bodyTtlSeconds ?? DEFAULT_BODY_TTL_SECONDS
    }

    /**
     * Returns the slim manifest. Cold/stale paths run `upstream` inside the
     * SharedBlobCache writer lock, publish every body key, and only then write
     * back the slim manifest.
     */
    async loadOrRefresh(upstream: () => Promise<ContextMillResource[]>): Promise<SlimManifest> {
        const bytes = await this.manifestCache.fetch(async () => {
            const entries = await upstream()
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
        })
        return JSON.parse(new TextDecoder().decode(bytes)) as SlimManifest
    }

    /**
     * Invalidate the slim manifest so the next `loadOrRefresh` is treated as
     * cold and fetches upstream. Use from miss-recovery paths — e.g. when a
     * body lookup returns null because Redis evicted it but the manifest is
     * still fresh, plain `loadOrRefresh` would short-circuit.
     */
    async invalidate(): Promise<void> {
        await Promise.all([this.redis.del(this.manifestCache.cacheKey), this.redis.del(this.manifestCache.freshKey)])
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
            return null
        }
        return JSON.parse(raw) as ResourceBody
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
