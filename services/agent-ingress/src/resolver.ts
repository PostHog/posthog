import { LRUCache } from 'lru-cache'

import { InternalApiClient, ResolvedRevision, logger } from '@posthog/agent-core'

export interface ResolverOptions {
    client: InternalApiClient
    ttlMs: number
    maxEntries?: number
    /**
     * Dev-only escape hatch. When provided, lookups try this in-memory map first
     * (keyed by `applicationId` AND by `${applicationSlug}${domainSuffix}`) before
     * falling through to the Internal API. Lets the local stack run without a wired
     * Django side. Loaded once from `AGENT_DEV_REVISIONS_PATH` in `index.ts`.
     */
    localRevisions?: Map<string, ResolvedRevision>
}

/**
 * Resolves an inbound host (or explicit application id) to the live `(application, revision)`.
 *
 * Backed by an LRU keyed on the resolution input; entries expire after `ttlMs` so promotions
 * propagate without needing an explicit invalidation channel. The Django side will eventually
 * gain an admin invalidation endpoint, but TTL is enough for v1.
 */
export class RevisionResolver {
    private readonly cache: LRUCache<string, ResolvedRevision>

    constructor(private readonly options: ResolverOptions) {
        this.cache = new LRUCache({
            max: options.maxEntries ?? 5_000,
            ttl: options.ttlMs,
        })
    }

    async resolveDomain(domain: string): Promise<ResolvedRevision | null> {
        const local = this.options.localRevisions?.get(`domain:${domain}`)
        if (local) {
            return local
        }
        return this.lookup(`domain:${domain}`, () => this.options.client.resolve({ domain }))
    }

    async resolveApplication(applicationId: string): Promise<ResolvedRevision | null> {
        const local = this.options.localRevisions?.get(`app:${applicationId}`)
        if (local) {
            return local
        }
        return this.lookup(`app:${applicationId}`, () => this.options.client.resolve({ applicationId }))
    }

    /** Manually evict a cache entry, used on promotion pings from Django. */
    invalidate(key: { domain?: string; applicationId?: string }): void {
        if (key.domain) {
            this.cache.delete(`domain:${key.domain}`)
        }
        if (key.applicationId) {
            this.cache.delete(`app:${key.applicationId}`)
        }
    }

    private async lookup(
        key: string,
        fetcher: () => Promise<ResolvedRevision | null>
    ): Promise<ResolvedRevision | null> {
        const cached = this.cache.get(key)
        if (cached) {
            return cached
        }
        try {
            const resolved = await fetcher()
            if (resolved) {
                this.cache.set(key, resolved)
            }
            return resolved
        } catch (err) {
            logger.error('RevisionResolver lookup failed', { key, error: String(err) })
            throw err
        }
    }
}
