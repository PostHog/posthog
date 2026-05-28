import { AgentSpecSchema } from '../spec/spec'
import { MemoryRevisionStore } from './revision-store'

describe('MemoryRevisionStore', () => {
    it('creates and looks up applications by slug', async () => {
        const store = new MemoryRevisionStore()
        const app = await store.createApplication({
            team_id: 1,
            slug: 'weekly-digest',
            name: 'Weekly Digest',
            description: '',
        })
        expect(await store.getApplicationBySlug(1, 'weekly-digest')).toEqual(app)
        expect(await store.getApplicationBySlug(2, 'weekly-digest')).toBeNull()
    })

    it('creates revisions in draft state, allows spec updates', async () => {
        const store = new MemoryRevisionStore()
        const app = await store.createApplication({ team_id: 1, slug: 'a', name: 'A', description: '' })
        const spec = AgentSpecSchema.parse({ model: 'claude-opus-4-7' })
        const rev = await store.createRevision({
            application_id: app.id,
            parent_revision_id: null,
            created_by_id: null,
            bundle_uri: 's3://x/rev/',
            spec,
        })
        expect(rev.state).toBe('draft')
        await store.updateSpec(rev.id, AgentSpecSchema.parse({ model: 'claude-sonnet-4-6' }))
        const updated = await store.getRevision(rev.id)
        expect(updated!.spec.model).toBe('claude-sonnet-4-6')
    })

    it('rejects spec updates on non-draft revisions', async () => {
        const store = new MemoryRevisionStore()
        const app = await store.createApplication({ team_id: 1, slug: 'a', name: 'A', description: '' })
        const spec = AgentSpecSchema.parse({ model: 'x' })
        const rev = await store.createRevision({
            application_id: app.id,
            parent_revision_id: null,
            created_by_id: null,
            bundle_uri: 's3://x/',
            spec,
        })
        await store.setRevisionState(rev.id, 'ready', 'deadbeef')
        await expect(store.updateSpec(rev.id, spec)).rejects.toThrow(/not a draft/)
    })

    it('setLiveRevision updates the application pointer', async () => {
        const store = new MemoryRevisionStore()
        const app = await store.createApplication({ team_id: 1, slug: 'a', name: 'A', description: '' })
        const rev = await store.createRevision({
            application_id: app.id,
            parent_revision_id: null,
            created_by_id: null,
            bundle_uri: 's3://x/',
            spec: AgentSpecSchema.parse({ model: 'x' }),
        })
        await store.setLiveRevision(app.id, rev.id)
        const fresh = await store.getApplication(app.id)
        expect(fresh!.live_revision_id).toBe(rev.id)
    })
})
