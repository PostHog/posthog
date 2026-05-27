import request from 'supertest'

import { AgentSpecSchema, MemoryRevisionStore, MemorySessionQueue } from '@posthog/agent-shared-v2'
import type { AgentApplication, AgentRevision } from '@posthog/agent-shared-v2'

import { MemorySessionEventBus } from './bus'
import { buildApp } from './server'

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
        spec: AgentSpecSchema.parse({
            model: 'x',
            triggers: [
                { type: 'chat', config: { require_auth: false } },
                { type: 'slack', config: {} },
                { type: 'webhook', config: { path: '/webhook' } },
                { type: 'mcp', config: {} },
            ],
        }),
    })
    await store.setRevisionState(rev.id, 'live')
    await store.setLiveRevision(app.id, rev.id)
    return { app, rev }
}

describe('ingress HTTP server (path mode)', () => {
    function mk(): {
        revisions: MemoryRevisionStore
        queue: MemorySessionQueue
        bus: MemorySessionEventBus
        app: ReturnType<typeof buildApp>
    } {
        const revisions = new MemoryRevisionStore()
        const queue = new MemorySessionQueue()
        const bus = new MemorySessionEventBus()
        const app = buildApp({
            revisions,
            queue,
            bus,
            teamId: 1,
            routingMode: 'path',
            pathPrefix: '/agents',
        })
        return { revisions, queue, bus, app }
    }

    it('GET /healthz returns ok', async () => {
        const { app } = mk()
        const res = await request(app).get('/healthz')
        expect(res.status).toBe(200)
        expect(res.body).toEqual({ ok: true })
    })

    it('404s an unknown agent slug', async () => {
        const { app } = mk()
        const res = await request(app).post('/agents/ghost/webhook').send({ data: 'x' })
        expect(res.status).toBe(404)
    })

    it('POST /run creates a chat session', async () => {
        const { revisions, queue, app } = mk()
        await seedApp(revisions, 'weekly-digest')
        const res = await request(app).post('/agents/weekly-digest/run').send({ message: 'hi', external_key: 'ext-1' })
        expect(res.status).toBe(200)
        expect(res.body.session_id).not.toBeUndefined()
        const session = await queue.get(res.body.session_id)
        expect(session!.conversation[0]).toMatchObject({ role: 'user', content: 'hi' })
    })

    it('POST /send buffers into pending_inputs (drained by runner at next turn)', async () => {
        const { revisions, queue, app } = mk()
        await seedApp(revisions, 'x')
        const createRes = await request(app).post('/agents/x/run').send({ message: 'first' })
        const sid = createRes.body.session_id
        const sendRes = await request(app).post('/agents/x/send').send({ session_id: sid, message: 'second' })
        expect(sendRes.status).toBe(200)
        const session = await queue.get(sid)
        expect(session!.conversation).toHaveLength(1)
        expect(session!.pending_inputs).toHaveLength(1)
    })

    it('POST /slack/events handles url_verification challenge', async () => {
        const { app } = mk()
        const res = await request(app)
            .post('/agents/foo/slack/events')
            .send({ type: 'url_verification', challenge: 'xyz' })
        expect(res.status).toBe(200)
        expect(res.body.challenge).toBe('xyz')
    })

    it('POST /slack/events with thread_ts uses externalKey for resume', async () => {
        const { revisions, queue, app } = mk()
        await seedApp(revisions, 'echo')
        const first = await request(app)
            .post('/agents/echo/slack/events')
            .send({
                type: 'event_callback',
                event: { type: 'message', channel: 'C01', user: 'U01', text: 'hi', ts: '1.0', thread_ts: '1.0' },
            })
        const second = await request(app)
            .post('/agents/echo/slack/events')
            .send({
                type: 'event_callback',
                event: { type: 'message', channel: 'C01', user: 'U01', text: 'follow', ts: '1.1', thread_ts: '1.0' },
            })
        expect(first.body.resumed).toBe(false)
        expect(second.body.resumed).toBe(true)
        expect(second.body.session_id).toBe(first.body.session_id)
        const session = await queue.get(first.body.session_id)
        // First message lands in conversation (fresh session). Second goes
        // into pending_inputs (resume of a still-live session).
        expect(session!.conversation).toHaveLength(1)
        expect(session!.pending_inputs).toHaveLength(1)
    })

    it('POST /webhook creates a session with body as content', async () => {
        const { revisions, queue, app } = mk()
        await seedApp(revisions, 'wh')
        const res = await request(app)
            .post('/agents/wh/webhook')
            .send({ payload: { x: 1 } })
        const session = await queue.get(res.body.session_id)
        expect(session!.conversation[0].content).toBe(JSON.stringify({ payload: { x: 1 } }))
    })

    it('POST /mcp initialize returns server info with slug', async () => {
        const { revisions, app } = mk()
        await seedApp(revisions, 'weekly-digest')
        const res = await request(app)
            .post('/agents/weekly-digest/mcp')
            .send({ jsonrpc: '2.0', id: 1, method: 'initialize' })
        expect(res.body.result.serverInfo.name).toBe('agent:weekly-digest')
    })

    it('POST /mcp tools/list returns the chat tool', async () => {
        const { revisions, app } = mk()
        await seedApp(revisions, 'x')
        const res = await request(app).post('/agents/x/mcp').send({ jsonrpc: '2.0', id: 1, method: 'tools/list' })
        expect(res.body.result.tools[0].name).toBe('chat')
    })

    it('POST /mcp tools/call name=chat enqueues a session', async () => {
        const { revisions, queue, app } = mk()
        await seedApp(revisions, 'x')
        const res = await request(app)
            .post('/agents/x/mcp')
            .send({
                jsonrpc: '2.0',
                id: 1,
                method: 'tools/call',
                params: { name: 'chat', arguments: { message: 'hi via mcp' } },
            })
        const parsed = JSON.parse(res.body.result.content[0].text)
        expect(parsed.session_id).not.toBeUndefined()
        const session = await queue.get(parsed.session_id)
        expect(session!.conversation[0].content).toBe('hi via mcp')
    })
})
