import { AgentSpecSchema, MemoryRevisionStore } from '@posthog/agent-shared'

import { makeAgentMcpResolver } from './agent-mcp-resolver'

const SPEC_WITH_MCP_TRIGGER = AgentSpecSchema.parse({
    model: 'claude-opus-4-7',
    triggers: [{ type: 'mcp', config: {} }],
})
const SPEC_WITHOUT_MCP_TRIGGER = AgentSpecSchema.parse({ model: 'claude-opus-4-7' })

const CTX = { teamId: 7, sessionId: 'sess-1' }

async function buildStoreWith(opts: {
    teamId: number
    slug: string
    spec?: typeof SPEC_WITH_MCP_TRIGGER
    /** When `false`, application is created but no revision is pinned live. */
    pinLive?: boolean
}): Promise<MemoryRevisionStore> {
    const store = new MemoryRevisionStore()
    const app = await store.createApplication({
        team_id: opts.teamId,
        slug: opts.slug,
        name: 'x',
        description: '',
    })
    const rev = await store.createRevision({
        application_id: app.id,
        parent_revision_id: null,
        created_by_id: null,
        bundle_uri: 'fs://x/',
        spec: opts.spec ?? SPEC_WITH_MCP_TRIGGER,
    })
    if (opts.pinLive !== false) {
        await store.setLiveRevision(app.id, rev.id)
    }
    return store
}

describe('makeAgentMcpResolver', () => {
    it('mints the ingress URL and the x-posthog-internal header for a healthy target', async () => {
        const revisions = await buildStoreWith({ teamId: 7, slug: 'weekly-digest' })
        const resolver = makeAgentMcpResolver({
            revisions,
            ingressBaseUrl: 'https://app.posthog.com',
            internalSecret: 'secret-shh',
        })
        const result = await resolver('weekly-digest', CTX)
        expect(result).toEqual({
            url: 'https://app.posthog.com/agents/weekly-digest/mcp',
            headers: { 'x-posthog-internal': 'secret-shh' },
        })
    })

    it('strips a trailing slash off the base URL so the resulting URL is canonical', async () => {
        const revisions = await buildStoreWith({ teamId: 7, slug: 'weekly-digest' })
        const resolver = makeAgentMcpResolver({
            revisions,
            ingressBaseUrl: 'https://app.posthog.com/',
            internalSecret: 'secret',
        })
        const result = await resolver('weekly-digest', CTX)
        expect(result.url).toBe('https://app.posthog.com/agents/weekly-digest/mcp')
    })

    it('URL-encodes the slug so a path-separator slug cannot escape the route', async () => {
        // Slugs are validated upstream, but the resolver shouldn't trust
        // its own input — if a future spec author smuggles `..` past the
        // validation we don't want to mint `/agents/../...`.
        const revisions = await buildStoreWith({ teamId: 7, slug: 'has slash' })
        const resolver = makeAgentMcpResolver({
            revisions,
            ingressBaseUrl: 'https://app.posthog.com',
            internalSecret: 'secret',
        })
        const result = await resolver('has slash', CTX)
        expect(result.url).toBe('https://app.posthog.com/agents/has%20slash/mcp')
    })

    it('throws agent_mcp_target_not_found when the target app does not exist on this team', async () => {
        const revisions = new MemoryRevisionStore()
        const resolver = makeAgentMcpResolver({
            revisions,
            ingressBaseUrl: 'https://app.posthog.com',
            internalSecret: 'secret',
        })
        await expect(resolver('weekly-digest', CTX)).rejects.toThrow(/agent_mcp_target_not_found/)
    })

    it('throws agent_mcp_target_not_found when the target exists on a DIFFERENT team', async () => {
        // Team isolation is the load-bearing invariant of the
        // `AgentMcpResolverContext.teamId` plumbing PR 6 added — make sure
        // a team-mismatched app fails closed, not silently routes.
        const revisions = await buildStoreWith({ teamId: 999, slug: 'weekly-digest' })
        const resolver = makeAgentMcpResolver({
            revisions,
            ingressBaseUrl: 'https://app.posthog.com',
            internalSecret: 'secret',
        })
        await expect(resolver('weekly-digest', { teamId: 7, sessionId: 'sess-1' })).rejects.toThrow(
            /agent_mcp_target_not_found/
        )
    })

    it('throws agent_mcp_target_no_live_revision when no revision is pinned live', async () => {
        const revisions = await buildStoreWith({ teamId: 7, slug: 'weekly-digest', pinLive: false })
        const resolver = makeAgentMcpResolver({
            revisions,
            ingressBaseUrl: 'https://app.posthog.com',
            internalSecret: 'secret',
        })
        await expect(resolver('weekly-digest', CTX)).rejects.toThrow(/agent_mcp_target_no_live_revision/)
    })

    it('throws agent_mcp_target_no_mcp_trigger when the live revision does not expose an mcp trigger', async () => {
        const revisions = await buildStoreWith({
            teamId: 7,
            slug: 'webhook-only',
            spec: SPEC_WITHOUT_MCP_TRIGGER,
        })
        const resolver = makeAgentMcpResolver({
            revisions,
            ingressBaseUrl: 'https://app.posthog.com',
            internalSecret: 'secret',
        })
        await expect(resolver('webhook-only', CTX)).rejects.toThrow(/agent_mcp_target_no_mcp_trigger/)
    })
})
