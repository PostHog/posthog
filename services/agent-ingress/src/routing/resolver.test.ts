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
        created_by_id: null,
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

    describe('revisionId override (draft invoke)', () => {
        it('resolves to the override revision even when the app has no live_revision', async () => {
            const store = new MemoryRevisionStore()
            // Bypass seedApp because it sets a live revision; we want a slug → app with a draft only.
            const app = await store.createApplication({ team_id: 1, slug: 'wip', name: 'wip', description: '' })
            const draft = await store.createRevision({
                application_id: app.id,
                parent_revision_id: null,
                created_by_id: null,
                bundle_uri: 's3://x/',
                spec: AgentSpecSchema.parse({ model: 'x' }),
            })
            const resolver = new RevisionResolver({ revisions: store, mode: 'path', pathPrefix: '/agents', teamId: 1 })
            const out = await resolver.resolveBySlug('wip', { revisionId: draft.id })
            expect(out!.revision.id).toBe(draft.id)
            expect(out!.revision.state).toBe('draft')
        })

        it('refuses a revisionId that belongs to a different application', async () => {
            const store = new MemoryRevisionStore()
            const { app: foreignApp } = await seedApp(store, 'other')
            // Make a draft revision under a different application.
            const foreignDraft = await store.createRevision({
                application_id: foreignApp.id,
                parent_revision_id: null,
                created_by_id: null,
                bundle_uri: 's3://x/',
                spec: AgentSpecSchema.parse({ model: 'x' }),
            })
            await seedApp(store, 'mine')
            const resolver = new RevisionResolver({ revisions: store, mode: 'path', pathPrefix: '/agents', teamId: 1 })
            expect(await resolver.resolveBySlug('mine', { revisionId: foreignDraft.id })).toBeNull()
        })

        it('refuses an archived revisionId', async () => {
            const store = new MemoryRevisionStore()
            const app = await store.createApplication({ team_id: 1, slug: 'archived-rev', name: 'x', description: '' })
            const archived = await store.createRevision({
                application_id: app.id,
                parent_revision_id: null,
                created_by_id: null,
                bundle_uri: 's3://x/',
                spec: AgentSpecSchema.parse({ model: 'x' }),
            })
            await store.setRevisionState(archived.id, 'archived')
            const resolver = new RevisionResolver({ revisions: store, mode: 'path', pathPrefix: '/agents', teamId: 1 })
            expect(await resolver.resolveBySlug('archived-rev', { revisionId: archived.id })).toBeNull()
        })

        it('returns null when the override revision id does not exist', async () => {
            const store = new MemoryRevisionStore()
            await seedApp(store, 'present')
            const resolver = new RevisionResolver({ revisions: store, mode: 'path', pathPrefix: '/agents', teamId: 1 })
            expect(
                await resolver.resolveBySlug('present', { revisionId: '00000000-0000-0000-0000-000000000000' })
            ).toBeNull()
        })
    })
})
