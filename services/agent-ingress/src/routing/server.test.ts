import request from 'supertest'

import { AgentSpecSchema, MemoryRevisionStore, MemorySessionQueue } from '@posthog/agent-shared'
import type { AgentApplication, AgentRevision } from '@posthog/agent-shared'
import { MemorySessionEventBus } from '@posthog/agent-shared'

import { buildApp } from './server'

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
        spec: AgentSpecSchema.parse({
            model: 'x',
            triggers: [
                { type: 'chat', config: { require_auth: false } },
                { type: 'slack', config: { trusted_workspaces: '*' } },
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

    // Trigger-edge validation: the chat trigger used to silently coerce a
    // missing / wrong-shaped `message` into the empty string, then enqueue a
    // session that died at the model layer. zod parsing at the edge turns
    // each of those into a clean 400 with the issue list.
    it('POST /run with empty message returns 400 with zod issues', async () => {
        const { revisions, app } = mk()
        await seedApp(revisions, 'x')
        const res = await request(app).post('/agents/x/run').send({ message: '' })
        expect(res.status).toBe(400)
        expect(res.body.error).toBe('invalid_body')
        expect(res.body.issues[0].path).toEqual(['message'])
    })

    it('POST /run wrapped in {input: ...} returns 400 (the exact mistake from authoring)', async () => {
        const { revisions, app } = mk()
        await seedApp(revisions, 'x')
        const res = await request(app)
            .post('/agents/x/run')
            .send({ input: { message: 'hi' } })
        expect(res.status).toBe(400)
        expect(res.body.error).toBe('invalid_body')
        expect(res.body.issues[0].path).toEqual(['message'])
    })

    it('POST /send with non-UUID session_id returns 400', async () => {
        const { revisions, app } = mk()
        await seedApp(revisions, 'x')
        const res = await request(app).post('/agents/x/send').send({ session_id: 'nope', message: 'hi' })
        expect(res.status).toBe(400)
        expect(res.body.error).toBe('invalid_body')
        expect(res.body.issues[0].path).toEqual(['session_id'])
    })

    // Schema-publish: every trigger the agent has should appear, with the
    // auth requirement resolved against the agent's `spec.auth` — callers
    // learn the full API surface (and how to authenticate to each route)
    // from one GET. No grepping the trigger source.
    it('GET /schemas cascades from spec.triggers across every trigger module', async () => {
        const { revisions, app } = mk()
        await seedApp(revisions, 'discoverable')
        const res = await request(app).get('/agents/discoverable/schemas')
        expect(res.status).toBe(200)
        expect(res.body.agent).toEqual({ slug: 'discoverable', name: 'discoverable' })
        const byType = Object.fromEntries(
            (res.body.triggers as Array<{ type: string; routes: unknown[] }>).map((t) => [t.type, t])
        )
        // seedApp wires all four triggers; the registry should publish all of them.
        expect(Object.keys(byType).sort()).toEqual(['chat', 'mcp', 'slack', 'webhook'])
    })

    it('GET /schemas publishes the chat trigger body shape + per-route auth', async () => {
        const { revisions, app } = mk()
        await seedApp(revisions, 'discoverable')
        const res = await request(app).get('/agents/discoverable/schemas')
        const chat = (res.body.triggers as Array<{ type: string; routes: unknown[] }>).find((t) => t.type === 'chat')!
        const routesByPath = Object.fromEntries(
            (
                chat.routes as Array<{
                    method: string
                    path: string
                    bodySchema?: { properties?: Record<string, unknown>; required?: string[] }
                    querySchema?: unknown
                    auth: { mode: string }
                }>
            ).map((r) => [`${r.method} ${r.path}`, r])
        )
        expect(routesByPath['POST /run'].bodySchema!.properties!.message).toMatchObject({
            type: 'string',
            minLength: 1,
        })
        expect(routesByPath['POST /run'].bodySchema!.required).toContain('message')
        // seedApp's agent has no custom auth → spec.auth.mode defaults to public
        // → every chat route advertises that to the caller.
        expect(routesByPath['POST /run'].auth).toEqual({ mode: 'public' })
        expect(routesByPath['GET /listen'].querySchema).not.toBeUndefined()
    })

    it('GET /schemas advertises slack signing auth on the slack route', async () => {
        const { revisions, app } = mk()
        await seedApp(revisions, 'discoverable')
        const res = await request(app).get('/agents/discoverable/schemas')
        const slack = (res.body.triggers as Array<{ type: string; routes: unknown[] }>).find((t) => t.type === 'slack')!
        const route = (slack.routes as Array<{ path: string; auth: { mode: string; header?: string } }>)[0]
        expect(route.path).toBe('/slack/events')
        expect(route.auth).toEqual({ mode: 'slack_signing', header: 'X-Slack-Signature' })
    })

    // Edge validation on the non-chat triggers — same pattern as chat, just
    // for the cases that actually have a contract worth enforcing.

    it('POST /webhook with a non-object body returns 400 (instead of seeding "[]")', async () => {
        const { revisions, app } = mk()
        await seedApp(revisions, 'wh')
        const res = await request(app).post('/agents/wh/webhook').send([])
        expect(res.status).toBe(400)
        expect(res.body.error).toBe('invalid_body')
    })

    it('POST /mcp with the wrong jsonrpc version returns 400', async () => {
        const { revisions, app } = mk()
        await seedApp(revisions, 'm')
        const res = await request(app).post('/agents/m/mcp').send({ jsonrpc: '1.0', id: 1, method: 'initialize' })
        expect(res.status).toBe(400)
        expect(res.body.error).toBe('invalid_body')
        expect(res.body.issues[0].path).toEqual(['jsonrpc'])
    })

    it('GET /mcp/stream without a session_id returns 400', async () => {
        const { revisions, app } = mk()
        await seedApp(revisions, 'm')
        const res = await request(app).get('/agents/m/mcp/stream')
        expect(res.status).toBe(400)
        expect(res.body.error).toBe('invalid_query')
    })

    it('GET /schemas 404s for an unknown agent', async () => {
        const { app } = mk()
        const res = await request(app).get('/agents/ghost/schemas')
        expect(res.status).toBe(404)
        expect(res.body.error).toBe('no_agent')
    })

    // Regression: malformed JSON used to produce express's default HTML
    // SyntaxError page. The global errorHandler now translates it to a
    // structured 400.
    it('POST /run with malformed JSON returns 400 invalid_json', async () => {
        const { revisions, app } = mk()
        await seedApp(revisions, 'x')
        const res = await request(app).post('/agents/x/run').set('Content-Type', 'application/json').send('{not json')
        expect(res.status).toBe(400)
        expect(res.body.error).toBe('invalid_json')
    })
})
