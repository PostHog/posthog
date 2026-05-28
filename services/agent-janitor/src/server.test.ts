import request from 'supertest'

import {
    AgentSession,
    AgentSpecSchema,
    MemoryBundleStore,
    MemoryRevisionStore,
    MemorySessionQueue,
} from '@posthog/agent-shared'

import { buildJanitorApp } from './server'

function session(id: string): AgentSession {
    return {
        id,
        application_id: 'app',
        revision_id: 'rev',
        team_id: 1,
        external_key: null,
        state: 'running',
        conversation: [{ role: 'user', content: 'hi', timestamp: Date.now() }],
        pending_inputs: [],
        principal: null,
        retry_count: 0,
        created_at: '2026-05-27',
        updated_at: '2026-05-27',
    }
}

describe('janitor HTTP', () => {
    function mk(): { queue: MemorySessionQueue; app: ReturnType<typeof buildJanitorApp> } {
        const queue = new MemorySessionQueue()
        const app = buildJanitorApp({
            queue,
            sweep: { queue, stuckRunningThresholdMs: 60_000 },
        })
        return { queue, app }
    }

    it('GET /healthz returns ok', async () => {
        const { app } = mk()
        const res = await request(app).get('/healthz')
        expect(res.status).toBe(200)
    })

    it('GET /sessions/:id returns session, 404 if missing', async () => {
        const { queue, app } = mk()
        await queue.enqueue(session('s1'))
        const ok = await request(app).get('/sessions/s1')
        expect(ok.status).toBe(200)
        expect(ok.body.id).toBe('s1')
        const miss = await request(app).get('/sessions/nope')
        expect(miss.status).toBe(404)
    })

    it('POST /sessions/:id/cancel marks failed', async () => {
        const { queue, app } = mk()
        await queue.enqueue(session('s2'))
        const res = await request(app).post('/sessions/s2/cancel')
        expect(res.status).toBe(200)
        expect((await queue.get('s2'))!.state).toBe('failed')
    })

    it('POST /sweep returns counts', async () => {
        const { app } = mk()
        const res = await request(app).post('/sweep')
        expect(res.status).toBe(200)
        expect(res.body).toEqual({ requeued: 0, poisoned: 0, failed: 0 })
    })

    it('enforces internal secret when configured', async () => {
        const queue = new MemorySessionQueue()
        const app = buildJanitorApp({
            queue,
            sweep: { queue, stuckRunningThresholdMs: 60_000 },
            internalSecret: 'topsecret',
        })
        const noAuth = await request(app).get('/sessions/x')
        expect(noAuth.status).toBe(401)
        const withAuth = await request(app).get('/sessions/x').set('x-internal-secret', 'topsecret')
        expect(withAuth.status).toBe(404) // session not found, but auth passed
    })

    /* ────────────────────────── catalog ────────────────────────── */

    it('GET /native_tools returns the registry catalog', async () => {
        const { app } = mk()
        const res = await request(app).get('/native_tools')
        expect(res.status).toBe(200)
        const ids = (res.body.tools as Array<{ id: string }>).map((t) => t.id)
        expect(ids).toEqual(expect.arrayContaining(['@posthog/query', '@posthog/meta-ask-for-input']))
    })

    /* ────────────────────────── revisions ────────────────────────── */

    async function mkRevisionApp(): Promise<{
        revisions: MemoryRevisionStore
        bundles: MemoryBundleStore
        app: ReturnType<typeof buildJanitorApp>
        revisionId: string
    }> {
        const revisions = new MemoryRevisionStore()
        const bundles = new MemoryBundleStore()
        const queue = new MemorySessionQueue()
        const apprec = await revisions.createApplication({ team_id: 1, slug: 'a', name: 'A', description: '' })
        const rev = await revisions.createRevision({
            application_id: apprec.id,
            parent_revision_id: null,
            created_by: 'u',
            bundle_uri: 'mem://b',
            spec: AgentSpecSchema.parse({ model: 'x' }),
        })
        const app = buildJanitorApp({
            queue,
            sweep: { queue, stuckRunningThresholdMs: 60_000 },
            revisions,
            bundles,
        })
        return { revisions, bundles, app, revisionId: rev.id }
    }

    it('GET /revisions/:id/manifest returns the file list + state', async () => {
        const { app, bundles, revisionId } = await mkRevisionApp()
        await bundles.write(revisionId, 'agent.md', 'hello')
        await bundles.write(revisionId, 'skills/research.md', 'be thorough')
        const res = await request(app).get(`/revisions/${revisionId}/manifest`)
        expect(res.status).toBe(200)
        expect(res.body.state).toBe('draft')
        const paths = (res.body.files as Array<{ path: string }>).map((f) => f.path).sort()
        expect(paths).toEqual(['agent.md', 'skills/research.md'])
    })

    it('PUT /revisions/:id/file writes and GET reads back', async () => {
        const { app, revisionId } = await mkRevisionApp()
        const put = await request(app)
            .put(`/revisions/${revisionId}/file?path=tools/wc/source.ts`)
            .send({ content: 'export default 1' })
        expect(put.status).toBe(200)
        const get = await request(app).get(`/revisions/${revisionId}/file?path=tools/wc/source.ts`)
        expect(get.status).toBe(200)
        expect(get.body.content).toBe('export default 1')
    })

    it('DELETE /revisions/:id/file removes the file', async () => {
        const { app, bundles, revisionId } = await mkRevisionApp()
        await bundles.write(revisionId, 'doomed.md', 'bye')
        const del = await request(app).delete(`/revisions/${revisionId}/file?path=doomed.md`)
        expect(del.status).toBe(200)
        expect(await bundles.exists(revisionId, 'doomed.md')).toBe(false)
    })

    it('GET /revisions/:id/bundle bulk-pulls every file', async () => {
        const { app, bundles, revisionId } = await mkRevisionApp()
        await bundles.write(revisionId, 'agent.md', 'a')
        await bundles.write(revisionId, 'skills/x.md', 'b')
        const res = await request(app).get(`/revisions/${revisionId}/bundle`)
        expect(res.status).toBe(200)
        expect(res.body.files).toEqual({ 'agent.md': 'a', 'skills/x.md': 'b' })
    })

    it('PUT /revisions/:id/bundle with mode=replace wipes and writes', async () => {
        const { app, bundles, revisionId } = await mkRevisionApp()
        await bundles.write(revisionId, 'old.md', 'gone')
        const res = await request(app)
            .put(`/revisions/${revisionId}/bundle`)
            .send({ files: { 'new.md': 'fresh', 'agent.md': 'top' }, mode: 'replace' })
        expect(res.status).toBe(200)
        const paths = (res.body.files as Array<{ path: string }>).map((f) => f.path).sort()
        expect(paths).toEqual(['agent.md', 'new.md'])
        expect(await bundles.exists(revisionId, 'old.md')).toBe(false)
    })

    it('PUT /revisions/:id/bundle with mode=merge upserts without wiping', async () => {
        const { app, bundles, revisionId } = await mkRevisionApp()
        await bundles.write(revisionId, 'keep.md', 'still here')
        const res = await request(app)
            .put(`/revisions/${revisionId}/bundle`)
            .send({ files: { 'added.md': 'new' }, mode: 'merge' })
        expect(res.status).toBe(200)
        const paths = (res.body.files as Array<{ path: string }>).map((f) => f.path).sort()
        expect(paths).toEqual(['added.md', 'keep.md'])
    })

    it('POST /revisions/:id/freeze flips state to ready and stamps sha256', async () => {
        const { app, bundles, revisions, revisionId } = await mkRevisionApp()
        await bundles.write(revisionId, 'agent.md', 'final')
        const res = await request(app).post(`/revisions/${revisionId}/freeze`)
        expect(res.status).toBe(200)
        expect(res.body.state).toBe('ready')
        expect(res.body.bundle_sha256).toMatch(/^[0-9a-f]{64}$/)
        const after = await revisions.getRevision(revisionId)
        expect(after!.state).toBe('ready')
        expect(after!.bundle_sha256).toBe(res.body.bundle_sha256)
    })

    it('refuses writes once the revision is frozen', async () => {
        const { app, bundles, revisionId } = await mkRevisionApp()
        await bundles.write(revisionId, 'agent.md', 'final')
        await request(app).post(`/revisions/${revisionId}/freeze`)
        const put = await request(app).put(`/revisions/${revisionId}/file?path=agent.md`).send({ content: 'x' })
        expect(put.status).toBe(409)
        expect(put.body.error).toBe('revision_not_editable')
    })

    it('POST /revisions/:id/clone_from copies every file from the source', async () => {
        const { app, bundles, revisions, revisionId } = await mkRevisionApp()
        // Make the existing revision the source — seed it with files, freeze it.
        await bundles.write(revisionId, 'agent.md', 'parent')
        await bundles.write(revisionId, 'skills/x.md', 'parent skill')
        await request(app).post(`/revisions/${revisionId}/freeze`)
        // Create a fresh draft to clone into.
        const apps = await revisions.listApplications(1)
        const draft = await revisions.createRevision({
            application_id: apps[0].id,
            parent_revision_id: revisionId,
            created_by: 'u',
            bundle_uri: 'mem://b2',
            spec: { model: 'x' } as never,
        })
        const res = await request(app)
            .post(`/revisions/${draft.id}/clone_from`)
            .send({ source_revision_id: revisionId })
        expect(res.status).toBe(200)
        const paths = (res.body.files as Array<{ path: string }>).map((f) => f.path).sort()
        expect(paths).toEqual(['agent.md', 'skills/x.md'])
    })

    it('returns 503 when the revision/bundle stores are not configured', async () => {
        const { app } = mk() // no revisions/bundles
        const res = await request(app).get('/revisions/00000000-0000-0000-0000-000000000000/manifest')
        expect(res.status).toBe(503)
    })
})
