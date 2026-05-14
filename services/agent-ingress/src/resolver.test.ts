import { ApplicationsRepository, ResolvedRevision } from '@posthog/agent-core'

import { RevisionResolver } from './resolver'

const DOMAIN_SUFFIX = '.agents.posthog.com'

function makeRevision(overrides: Partial<ResolvedRevision> = {}): ResolvedRevision {
    return {
        applicationId: 'b1f3d6e4-4c2a-4b0e-9d5a-1c9f7e1d8a01',
        applicationSlug: 'analytics-bot',
        teamId: 7,
        revisionId: 'b1f3d6e4-4c2a-4b0e-9d5a-1c9f7e1d8a02',
        revisionState: 'ready',
        bundleS3Key: 's3://bundles/abc',
        bundleSha256: 'abcd',
        topLevelConfig: {},
        parsedManifest: null,
        auth: { mode: 'public' },
        ...overrides,
    }
}

interface FakeRepoCalls {
    domains: string[]
    applications: string[]
}

function makeFakeRepository(reply: ResolvedRevision | null): {
    repository: ApplicationsRepository
    calls: FakeRepoCalls
} {
    const calls: FakeRepoCalls = { domains: [], applications: [] }
    const repository = {
        resolveByDomain: async (domain: string) => {
            calls.domains.push(domain)
            return reply
        },
        resolveById: async (applicationId: string) => {
            calls.applications.push(applicationId)
            return reply
        },
    } as unknown as ApplicationsRepository
    return { repository, calls }
}

describe('RevisionResolver', () => {
    it('caches the first lookup and serves subsequent calls from the LRU', async () => {
        const { repository, calls } = makeFakeRepository(makeRevision())
        const resolver = new RevisionResolver({ repository, ttlMs: 60_000, domainSuffix: DOMAIN_SUFFIX })

        await resolver.resolveDomain('analytics-bot.agents.posthog.com')
        await resolver.resolveDomain('analytics-bot.agents.posthog.com')
        await resolver.resolveDomain('analytics-bot.agents.posthog.com')

        expect(calls.domains).toEqual(['analytics-bot.agents.posthog.com'])
    })

    it('separates the domain and application keyspaces', async () => {
        const { repository, calls } = makeFakeRepository(makeRevision())
        const resolver = new RevisionResolver({ repository, ttlMs: 60_000, domainSuffix: DOMAIN_SUFFIX })

        await resolver.resolveDomain('analytics-bot.agents.posthog.com')
        await resolver.resolveApplication('b1f3d6e4-4c2a-4b0e-9d5a-1c9f7e1d8a01')

        // Hitting the same domain a second time uses the cache; hitting the same applicationId
        // through resolveApplication does not (different keyspace).
        await resolver.resolveDomain('analytics-bot.agents.posthog.com')
        await resolver.resolveApplication('b1f3d6e4-4c2a-4b0e-9d5a-1c9f7e1d8a01')

        expect(calls.domains).toEqual(['analytics-bot.agents.posthog.com'])
        expect(calls.applications).toEqual(['b1f3d6e4-4c2a-4b0e-9d5a-1c9f7e1d8a01'])
    })

    it('does not cache null replies — keeps trying on subsequent lookups', async () => {
        const { repository, calls } = makeFakeRepository(null)
        const resolver = new RevisionResolver({ repository, ttlMs: 60_000, domainSuffix: DOMAIN_SUFFIX })

        await resolver.resolveDomain('missing.agents.posthog.com')
        await resolver.resolveDomain('missing.agents.posthog.com')

        // Avoids caching a stale 404 between deploys.
        expect(calls.domains.length).toBeGreaterThan(1)
    })

    it('expires entries after the TTL', async () => {
        const { repository, calls } = makeFakeRepository(makeRevision())
        const resolver = new RevisionResolver({ repository, ttlMs: 1, domainSuffix: DOMAIN_SUFFIX })

        await resolver.resolveDomain('analytics-bot.agents.posthog.com')
        // Wait past the TTL.
        await new Promise<void>((resolve) => setTimeout(resolve, 10))
        await resolver.resolveDomain('analytics-bot.agents.posthog.com')

        expect(calls.domains).toEqual(['analytics-bot.agents.posthog.com', 'analytics-bot.agents.posthog.com'])
    })

    it('invalidate() evicts the cached entry for a domain', async () => {
        const { repository, calls } = makeFakeRepository(makeRevision())
        const resolver = new RevisionResolver({ repository, ttlMs: 60_000, domainSuffix: DOMAIN_SUFFIX })

        await resolver.resolveDomain('analytics-bot.agents.posthog.com')
        resolver.invalidate({ domain: 'analytics-bot.agents.posthog.com' })
        await resolver.resolveDomain('analytics-bot.agents.posthog.com')

        expect(calls.domains).toEqual(['analytics-bot.agents.posthog.com', 'analytics-bot.agents.posthog.com'])
    })

    it('invalidate() evicts only the requested key', async () => {
        const { repository, calls } = makeFakeRepository(makeRevision())
        const resolver = new RevisionResolver({ repository, ttlMs: 60_000, domainSuffix: DOMAIN_SUFFIX })

        await resolver.resolveDomain('a.agents.posthog.com')
        await resolver.resolveDomain('b.agents.posthog.com')
        resolver.invalidate({ domain: 'a.agents.posthog.com' })

        await resolver.resolveDomain('a.agents.posthog.com')
        await resolver.resolveDomain('b.agents.posthog.com')

        // a was invalidated and re-fetched; b stayed cached.
        expect(calls.domains).toEqual(['a.agents.posthog.com', 'b.agents.posthog.com', 'a.agents.posthog.com'])
    })

    it('propagates errors from the repository and does not cache the failure', async () => {
        let attempt = 0
        const repository = {
            resolveByDomain: async () => {
                attempt += 1
                throw new Error(`boom ${attempt}`)
            },
            resolveById: async () => null,
        } as unknown as ApplicationsRepository
        const resolver = new RevisionResolver({ repository, ttlMs: 60_000, domainSuffix: DOMAIN_SUFFIX })

        await expect(resolver.resolveDomain('x.agents.posthog.com')).rejects.toThrow('boom 1')
        await expect(resolver.resolveDomain('x.agents.posthog.com')).rejects.toThrow('boom 2')
    })
})
