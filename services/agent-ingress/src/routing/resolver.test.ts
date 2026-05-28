import { AgentSpecSchema, MemoryRevisionStore } from '@posthog/agent-shared'
import { AgentApplication, AgentRevision } from '@posthog/agent-shared'

import { AmbiguousRevisionError, RevisionResolver } from './resolver'

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

    describe('slug-with-revision-suffix (local-dev form)', () => {
        // The memory store mints `rev_1`-style ids that don't match the 8-hex
        // regex. Stamp real UUID-shaped ids onto revisions for these tests by
        // editing the internal map directly — the resolver only cares about
        // the contract.
        function rebrandRevisionId(store: MemoryRevisionStore, oldId: string, newId: string): void {
            const map = (store as unknown as { revs: Map<string, AgentRevision> }).revs
            const rev = map.get(oldId)
            if (!rev) {
                throw new Error(`revision ${oldId} not found`)
            }
            rev.id = newId
            map.delete(oldId)
            map.set(newId, rev)
        }

        it('resolves <slug>-<8-hex prefix> to a single revision under that app', async () => {
            const store = new MemoryRevisionStore()
            const app = await store.createApplication({ team_id: 1, slug: 'preview', name: 'preview', description: '' })
            const rev = await store.createRevision({
                application_id: app.id,
                parent_revision_id: null,
                created_by_id: null,
                bundle_uri: 's3://x/',
                spec: AgentSpecSchema.parse({ model: 'x' }),
            })
            rebrandRevisionId(store, rev.id, '019e6f25-0185-7814-b4d8-882a429da835')
            const resolver = new RevisionResolver({ revisions: store, mode: 'path', pathPrefix: '/agents', teamId: 1 })
            const out = await resolver.resolveBySlug('preview-019e6f25')
            expect(out!.revision.id).toBe('019e6f25-0185-7814-b4d8-882a429da835')
        })

        it('throws AmbiguousRevisionError when the prefix matches multiple revisions', async () => {
            const store = new MemoryRevisionStore()
            const app = await store.createApplication({ team_id: 1, slug: 'preview', name: 'preview', description: '' })
            const revA = await store.createRevision({
                application_id: app.id,
                parent_revision_id: null,
                created_by_id: null,
                bundle_uri: 's3://x/',
                spec: AgentSpecSchema.parse({ model: 'x' }),
            })
            const revB = await store.createRevision({
                application_id: app.id,
                parent_revision_id: null,
                created_by_id: null,
                bundle_uri: 's3://x/',
                spec: AgentSpecSchema.parse({ model: 'x' }),
            })
            rebrandRevisionId(store, revA.id, '019e6f25-0185-7814-b4d8-aaaaaaaaaaaa')
            rebrandRevisionId(store, revB.id, '019e6f25-0185-7814-b4d8-bbbbbbbbbbbb')
            const resolver = new RevisionResolver({ revisions: store, mode: 'path', pathPrefix: '/agents', teamId: 1 })
            await expect(resolver.resolveBySlug('preview-019e6f25')).rejects.toBeInstanceOf(AmbiguousRevisionError)
        })

        it('falls back to verbatim slug when no application has the base slug', async () => {
            const store = new MemoryRevisionStore()
            // App's slug ends in 8 hex chars but the slug itself is the full string.
            // The 8-hex regex would split as ('unrelated', 'abcdef12'), but there's
            // no app called 'unrelated' — so the resolver falls through to verbatim.
            const app = await store.createApplication({
                team_id: 1,
                slug: 'unrelated-abcdef12',
                name: 'verbatim',
                description: '',
            })
            const rev = await store.createRevision({
                application_id: app.id,
                parent_revision_id: null,
                created_by_id: null,
                bundle_uri: 's3://x/',
                spec: AgentSpecSchema.parse({ model: 'x' }),
            })
            await store.setRevisionState(rev.id, 'live')
            await store.setLiveRevision(app.id, rev.id)
            const resolver = new RevisionResolver({ revisions: store, mode: 'path', pathPrefix: '/agents', teamId: 1 })
            const out = await resolver.resolveBySlug('unrelated-abcdef12')
            expect(out!.application.id).toBe(app.id)
        })

        it('treats archived suffix matches as non-matches (then falls through to verbatim)', async () => {
            const store = new MemoryRevisionStore()
            const app = await store.createApplication({
                team_id: 1,
                slug: 'with-archived',
                name: 'x',
                description: '',
            })
            const rev = await store.createRevision({
                application_id: app.id,
                parent_revision_id: null,
                created_by_id: null,
                bundle_uri: 's3://x/',
                spec: AgentSpecSchema.parse({ model: 'x' }),
            })
            rebrandRevisionId(store, rev.id, '019e6f25-0000-0000-0000-000000000000')
            await store.setRevisionState('019e6f25-0000-0000-0000-000000000000', 'archived')
            const resolver = new RevisionResolver({ revisions: store, mode: 'path', pathPrefix: '/agents', teamId: 1 })
            // Falls through to verbatim slug, which has no live_revision → null.
            expect(await resolver.resolveBySlug('with-archived-019e6f25')).toBeNull()
        })
    })
})
