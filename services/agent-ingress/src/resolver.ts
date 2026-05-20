import { LRUCache } from 'lru-cache'

import { ApplicationsRepository, ResolvedRevision, logger } from '@posthog/agent-core'

export interface ResolverOptions {
    repository: ApplicationsRepository
    ttlMs: number
    maxEntries?: number
    /** Suffix used to strip the slug out of an inbound `*.agents.posthog.com` host. */
    domainSuffix: string
}

/**
 * Resolves an inbound host (or explicit application id) to the live `(application, revision)`.
 *
 * Reads directly from the main posthog Postgres via `ApplicationsRepository`. Results are
 * cached in an LRU keyed on the resolution input; entries expire after `ttlMs` so
 * promotions propagate without an explicit invalidation channel.
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
        return this.lookup(`domain:${domain}`, () =>
            this.options.repository.resolveByDomain(domain, this.options.domainSuffix)
        )
    }

    async resolveApplication(applicationId: string): Promise<ResolvedRevision | null> {
        return this.lookup(`app:${applicationId}`, () => this.options.repository.resolveById(applicationId))
    }

    /**
     * Resolve by bare application slug — used by path-based routing
     * (`/agents/<slug>/...`). Domain mode prefers `resolveDomain` so the cache
     * key matches the inbound Host header.
     */
    async resolveSlug(slug: string): Promise<ResolvedRevision | null> {
        return this.lookup(`slug:${slug}`, () => this.options.repository.resolveBySlug(slug))
    }

    /** Manually evict a cache entry — useful when Django wants to push an invalidation. */
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
            logger.error({ err, key }, 'RevisionResolver lookup failed')
            throw err
        }
    }
}
