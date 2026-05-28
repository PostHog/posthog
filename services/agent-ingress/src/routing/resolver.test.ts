import { AgentSpecSchema, MemoryRevisionStore } from '@posthog/agent-shared'
import { AgentApplication, AgentRevision } from '@posthog/agent-shared'

import { RevisionResolver } from './resolver'

async function seedApp(
    store: MemoryRevisionStore,
    slug: string
): Promise<{ app: AgentApplication; rev: AgentRevision }> {
    const app = await store.createApplication({ team_id: 1, slug, name: slug, description: '' })
    const rev = await store.createRevision({
        application_id: app.id,
        parent_revision_id: null,
        created_by: 'u',
        bundle_uri: 's3://x/',
        spec: AgentSpecSchema.parse({ model: 'x' }),
    })
    await store.setRevisionState(rev.id, 'live')
    await store.setLiveRevision(app.id, rev.id)
    return { app, rev }
}

describe('RevisionResolver', () => {
    it('resolves in path mode', async () => {
        const store = new MemoryRevisionStore()
        const { app } = await seedApp(store, 'weekly-digest')
        const resolver = new RevisionResolver({ revisions: store, mode: 'path', pathPrefix: '/agents', teamId: 1 })
        const out = await resolver.resolveFromHostAndPath(undefined, '/agents/weekly-digest/slack/events')
        expect(out!.application.id).toBe(app.id)
    })

    it('resolves in domain mode', async () => {
        const store = new MemoryRevisionStore()
        await seedApp(store, 'weekly-digest')
        const resolver = new RevisionResolver({
            revisions: store,
            mode: 'domain',
            domainSuffix: '.agents.posthog.com',
            teamId: 1,
        })
        const out = await resolver.resolveFromHostAndPath('weekly-digest.agents.posthog.com', '/slack/events')
        expect(out!.application.slug).toBe('weekly-digest')
    })

    it('returns null for unknown slug', async () => {
        const store = new MemoryRevisionStore()
        const resolver = new RevisionResolver({ revisions: store, mode: 'path', pathPrefix: '/agents', teamId: 1 })
        expect(await resolver.resolveFromHostAndPath(undefined, '/agents/ghost/slack')).toBeNull()
    })

    it('returns null for archived or unlive applications', async () => {
        const store = new MemoryRevisionStore()
        const { app } = await seedApp(store, 'abandoned')
        await store.archiveApplication(app.id)
        const resolver = new RevisionResolver({ revisions: store, mode: 'path', pathPrefix: '/agents', teamId: 1 })
        expect(await resolver.resolveFromHostAndPath(undefined, '/agents/abandoned/x')).toBeNull()
    })
})
