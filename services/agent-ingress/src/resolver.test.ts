import { InternalApiClient, ResolvedRevision } from '@posthog/agent-core'

import { RevisionResolver } from './resolver'

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

interface FakeClientCalls {
    domains: string[]
    applications: string[]
}

function makeFakeClient(reply: ResolvedRevision | null): {
    client: InternalApiClient
    calls: FakeClientCalls
} {
    const calls: FakeClientCalls = { domains: [], applications: [] }
    const client = {
        resolve: async ({ domain, applicationId }: { domain?: string; applicationId?: string }) => {
            if (domain) {
                calls.domains.push(domain)
            }
            if (applicationId) {
                calls.applications.push(applicationId)
            }
            return reply
        },
    } as unknown as InternalApiClient
    return { client, calls }
}

describe('RevisionResolver', () => {
    it('caches the first lookup and serves subsequent calls from the LRU', async () => {
        const { client, calls } = makeFakeClient(makeRevision())
        const resolver = new RevisionResolver({ client, ttlMs: 60_000 })

        await resolver.resolveDomain('analytics-bot.agents.posthog.com')
        await resolver.resolveDomain('analytics-bot.agents.posthog.com')
        await resolver.resolveDomain('analytics-bot.agents.posthog.com')

        expect(calls.domains).toEqual(['analytics-bot.agents.posthog.com'])
    })

    it('separates the domain and application keyspaces', async () => {
        const { client, calls } = makeFakeClient(makeRevision())
        const resolver = new RevisionResolver({ client, ttlMs: 60_000 })

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
        const { client, calls } = makeFakeClient(null)
        const resolver = new RevisionResolver({ client, ttlMs: 60_000 })

        await resolver.resolveDomain('missing.agents.posthog.com')
        await resolver.resolveDomain('missing.agents.posthog.com')

        // Avoids caching a stale 404 between deploys.
        expect(calls.domains.length).toBeGreaterThan(1)
    })

    it('expires entries after the TTL', async () => {
        const { client, calls } = makeFakeClient(makeRevision())
        const resolver = new RevisionResolver({ client, ttlMs: 1 })

        await resolver.resolveDomain('analytics-bot.agents.posthog.com')
        // Wait past the TTL.
        await new Promise<void>((resolve) => setTimeout(resolve, 10))
        await resolver.resolveDomain('analytics-bot.agents.posthog.com')

        expect(calls.domains).toEqual(['analytics-bot.agents.posthog.com', 'analytics-bot.agents.posthog.com'])
    })

    it('invalidate() evicts the cached entry for a domain', async () => {
        const { client, calls } = makeFakeClient(makeRevision())
        const resolver = new RevisionResolver({ client, ttlMs: 60_000 })

        await resolver.resolveDomain('analytics-bot.agents.posthog.com')
        resolver.invalidate({ domain: 'analytics-bot.agents.posthog.com' })
        await resolver.resolveDomain('analytics-bot.agents.posthog.com')

        expect(calls.domains).toEqual(['analytics-bot.agents.posthog.com', 'analytics-bot.agents.posthog.com'])
    })

    it('invalidate() evicts only the requested key', async () => {
        const { client, calls } = makeFakeClient(makeRevision())
        const resolver = new RevisionResolver({ client, ttlMs: 60_000 })

        await resolver.resolveDomain('a.agents.posthog.com')
        await resolver.resolveDomain('b.agents.posthog.com')
        resolver.invalidate({ domain: 'a.agents.posthog.com' })

        await resolver.resolveDomain('a.agents.posthog.com')
        await resolver.resolveDomain('b.agents.posthog.com')

        // a was invalidated and re-fetched; b stayed cached.
        expect(calls.domains).toEqual(['a.agents.posthog.com', 'b.agents.posthog.com', 'a.agents.posthog.com'])
    })

    it('propagates errors from the client and does not cache the failure', async () => {
        let attempt = 0
        const client = {
            resolve: async () => {
                attempt += 1
                throw new Error(`boom ${attempt}`)
            },
        } as unknown as InternalApiClient
        const resolver = new RevisionResolver({ client, ttlMs: 60_000 })

        await expect(resolver.resolveDomain('x.agents.posthog.com')).rejects.toThrow('boom 1')
        await expect(resolver.resolveDomain('x.agents.posthog.com')).rejects.toThrow('boom 2')
    })
})
