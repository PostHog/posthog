import { createHmac } from 'crypto'
import request from 'supertest'

import { AgentSpecSchema, MemoryRevisionStore, MemorySessionQueue } from '@posthog/agent-shared'
import type { AgentApplication, AgentRevision } from '@posthog/agent-shared'
import { MemorySessionEventBus } from '@posthog/agent-shared'

import { buildApp } from './server'

const TEST_SLACK_SECRET = 'test-slack-secret'

/**
 * Mints the `(timestamp, signature)` pair Slack would send for a given body.
 * Slack signs `v0:<ts>:<rawBody>` with the shared signing secret; the ingress
 * verifies the exact same HMAC. Used by every `/slack/*` test case below
 * since every Slack route requires a verified signature now.
 */
function signSlack(body: string, secret = TEST_SLACK_SECRET): { ts: string; sig: string } {
    const ts = String(Math.floor(Date.now() / 1000))
    const mac = createHmac('sha256', secret).update(`v0:${ts}:${body}`).digest('hex')
    return { ts, sig: `v0=${mac}` }
}

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
            // In-memory resolver: returns the test secret for every
            // `(secretRef, application)` lookup. Models the
            // "PostHog runs one Slack app for everything" deployment without
            // needing each fixture to populate an `encrypted_env`.
            slackSigningSecretResolver: {
                async resolve(): Promise<string | null> {
                    return TEST_SLACK_SECRET
                },
            },
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
        const { revisions, app } = mk()
        // Slack signs url_verification with the same signing secret the agent
        // configures, so the agent has to exist + the resolver has to return
        // the secret before the challenge round-trip works.
        await seedApp(revisions, 'foo')
        const body = JSON.stringify({ type: 'url_verification', challenge: 'xyz' })
        const { ts, sig } = signSlack(body)
        const res = await request(app)
            .post('/agents/foo/slack/events')
            .set('content-type', 'application/json')
            .set('x-slack-request-timestamp', ts)
            .set('x-slack-signature', sig)
            .send(body)
        expect(res.status).toBe(200)
        expect(res.body.challenge).toBe('xyz')
    })

    it('POST /slack/events with thread_ts uses externalKey for resume', async () => {
        const { revisions, queue, app } = mk()
        await seedApp(revisions, 'echo')
        const firstBody = JSON.stringify({
            type: 'event_callback',
            event: { type: 'message', channel: 'C01', user: 'U01', text: 'hi', ts: '1.0', thread_ts: '1.0' },
        })
        const firstSig = signSlack(firstBody)
        const first = await request(app)
            .post('/agents/echo/slack/events')
            .set('content-type', 'application/json')
            .set('x-slack-request-timestamp', firstSig.ts)
            .set('x-slack-signature', firstSig.sig)
            .send(firstBody)
        const secondBody = JSON.stringify({
            type: 'event_callback',
            event: { type: 'message', channel: 'C01', user: 'U01', text: 'follow', ts: '1.1', thread_ts: '1.0' },
        })
        const secondSig = signSlack(secondBody)
        const second = await request(app)
            .post('/agents/echo/slack/events')
            .set('content-type', 'application/json')
            .set('x-slack-request-timestamp', secondSig.ts)
            .set('x-slack-signature', secondSig.sig)
            .send(secondBody)
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

    it('POST /mcp tools/list returns the ask tool', async () => {
        const { revisions, app } = mk()
        await seedApp(revisions, 'x')
        const res = await request(app).post('/agents/x/mcp').send({ jsonrpc: '2.0', id: 1, method: 'tools/list' })
        expect(res.body.result.tools[0].name).toBe('ask')
        // Inputs include the optional session_id for continuation.
        expect(res.body.result.tools[0].inputSchema.properties.session_id).not.toBeUndefined()
    })

    it('POST /mcp tools/call name=ask enqueues a session', async () => {
        const { revisions, queue, app } = mk()
        await seedApp(revisions, 'x')
        const res = await request(app)
            .post('/agents/x/mcp')
            .send({
                jsonrpc: '2.0',
                id: 1,
                method: 'tools/call',
                params: { name: 'ask', arguments: { message: 'hi via mcp' } },
            })
        const parsed = JSON.parse(res.body.result.content[0].text)
        expect(parsed.session_id).not.toBeUndefined()
        expect(parsed.state).toBe('queued')
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
                    auth: { modes?: Array<{ type: string }>; mode?: string }
                }>
            ).map((r) => [`${r.method} ${r.path}`, r])
        )
        expect(routesByPath['POST /run'].bodySchema!.properties!.message).toMatchObject({
            type: 'string',
            minLength: 1,
        })
        expect(routesByPath['POST /run'].bodySchema!.required).toContain('message')
        // seedApp's agent has no custom auth → spec.auth.modes defaults to
        // [{ type: 'public' }] → every chat route advertises that verbatim.
        expect(routesByPath['POST /run'].auth).toEqual({ modes: [{ type: 'public' }] })
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

    it('POST /mcp initialize mints an Mcp-Session-Id when the client did not send one', async () => {
        const { revisions, app } = mk()
        await seedApp(revisions, 'x')
        const res = await request(app).post('/agents/x/mcp').send({ jsonrpc: '2.0', id: 1, method: 'initialize' })
        // Standard streamable-HTTP session header — real MCP clients pick
        // this up and echo it on every subsequent request.
        const minted = res.headers['mcp-session-id'] as string | undefined
        expect(minted).toMatch(/^[0-9a-f-]{36}$/)
    })

    it('POST /mcp initialize does NOT re-mint when the client already sent an Mcp-Session-Id', async () => {
        const { revisions, app } = mk()
        await seedApp(revisions, 'x')
        const res = await request(app)
            .post('/agents/x/mcp')
            .set('Mcp-Session-Id', 'client-supplied')
            .send({ jsonrpc: '2.0', id: 1, method: 'initialize' })
        // Server only mints when missing — client's id wins.
        expect(res.headers['mcp-session-id']).toBeUndefined()
    })

    it('POST /mcp tools/call ask with session_id continues an existing session', async () => {
        const { revisions, queue, app } = mk()
        await seedApp(revisions, 'x')
        const initial = await request(app)
            .post('/agents/x/mcp')
            .send({
                jsonrpc: '2.0',
                id: 1,
                method: 'tools/call',
                params: { name: 'ask', arguments: { message: 'first' } },
            })
        const sid = JSON.parse(initial.body.result.content[0].text).session_id as string
        // Mark the queue session running so it isn't terminal — continuation
        // appends into pending_inputs.
        await queue.update(sid, { state: 'running' })
        const followup = await request(app)
            .post('/agents/x/mcp')
            .send({
                jsonrpc: '2.0',
                id: 2,
                method: 'tools/call',
                params: { name: 'ask', arguments: { message: 'second', session_id: sid } },
            })
        expect(JSON.parse(followup.body.result.content[0].text).session_id).toBe(sid)
        const after = await queue.get(sid)
        // Original conversation seed + the queued follow-up.
        expect(after!.conversation).toHaveLength(1)
        expect(after!.pending_inputs).toHaveLength(1)
        expect(after!.pending_inputs[0].content).toBe('second')
    })

    it('POST /mcp tools/call ask returns invalid_params for a missing message', async () => {
        const { revisions, app } = mk()
        await seedApp(revisions, 'x')
        const res = await request(app)
            .post('/agents/x/mcp')
            .send({
                jsonrpc: '2.0',
                id: 1,
                method: 'tools/call',
                params: { name: 'ask', arguments: {} },
            })
        expect(res.body.error.code).toBe(-32602)
    })

    it('POST /mcp tools/call rejects unknown tool name', async () => {
        const { revisions, app } = mk()
        await seedApp(revisions, 'x')
        const res = await request(app)
            .post('/agents/x/mcp')
            .send({
                jsonrpc: '2.0',
                id: 1,
                method: 'tools/call',
                params: { name: 'shout', arguments: { message: 'hi' } },
            })
        expect(res.body.error.code).toBe(-32601)
    })

    it('POST /mcp resources/list scopes by Mcp-Session-Id header on a public agent', async () => {
        const { revisions, app } = mk()
        await seedApp(revisions, 'x')
        // Client A creates a session, tagged with its Mcp-Session-Id header.
        const aCreate = await request(app)
            .post('/agents/x/mcp')
            .set('Mcp-Session-Id', 'client-A')
            .send({
                jsonrpc: '2.0',
                id: 1,
                method: 'tools/call',
                params: { name: 'ask', arguments: { message: 'from A' } },
            })
        const aSessionId = JSON.parse(aCreate.body.result.content[0].text).session_id as string
        // Client B does the same with its own header.
        const bCreate = await request(app)
            .post('/agents/x/mcp')
            .set('Mcp-Session-Id', 'client-B')
            .send({
                jsonrpc: '2.0',
                id: 1,
                method: 'tools/call',
                params: { name: 'ask', arguments: { message: 'from B' } },
            })
        const bSessionId = JSON.parse(bCreate.body.result.content[0].text).session_id as string
        // resources/list as A: only A's session shows up.
        const listA = await request(app)
            .post('/agents/x/mcp')
            .set('Mcp-Session-Id', 'client-A')
            .send({ jsonrpc: '2.0', id: 1, method: 'resources/list' })
        const aUris = (listA.body.result.resources as Array<{ uri: string }>).map((r) => r.uri)
        expect(aUris).toContain(`agent://session/${aSessionId}`)
        expect(aUris).not.toContain(`agent://session/${bSessionId}`)
        // A client with no Mcp-Session-Id sees nothing in list (security
        // default — prevents enumeration of other clients' sessions on a
        // public agent). It can still read by URI if it has the id.
        const listAnon = await request(app)
            .post('/agents/x/mcp')
            .send({ jsonrpc: '2.0', id: 1, method: 'resources/list' })
        expect(listAnon.body.result.resources).toEqual([])
    })

    it('POST /mcp resources/read on a public agent allows reads by URI possession', async () => {
        // Capability model — possession of the agent://session/<uuid> URI
        // is the secret. A different anonymous client (no header, no
        // principal) can read the session if it has the id. The 122 bits
        // of UUID entropy prevent guessing.
        const { revisions, app } = mk()
        await seedApp(revisions, 'x')
        const create = await request(app)
            .post('/agents/x/mcp')
            .set('Mcp-Session-Id', 'creator')
            .send({
                jsonrpc: '2.0',
                id: 1,
                method: 'tools/call',
                params: { name: 'ask', arguments: { message: 'mine' } },
            })
        const sessionId = JSON.parse(create.body.result.content[0].text).session_id as string
        // Same client reads — works.
        const owner = await request(app)
            .post('/agents/x/mcp')
            .set('Mcp-Session-Id', 'creator')
            .send({
                jsonrpc: '2.0',
                id: 1,
                method: 'resources/read',
                params: { uri: `agent://session/${sessionId}` },
            })
        expect(owner.body.result.contents[0].text).toContain(sessionId)
    })

    it('POST /mcp respects spec.auth — a pat-gated agent rejects unauthenticated calls', async () => {
        const { revisions, app } = mk()
        // Seed an agent with PAT auth (default app is public).
        const store = revisions
        const agentApp = await store.createApplication({
            team_id: 1,
            slug: 'gated',
            name: 'gated',
            description: '',
        })
        const rev = await store.createRevision({
            application_id: agentApp.id,
            parent_revision_id: null,
            created_by_id: null,
            bundle_uri: 's3://x/',
            spec: AgentSpecSchema.parse({
                model: 'x',
                triggers: [{ type: 'mcp', config: {} }],
                auth: { modes: [{ type: 'pat' }] },
            }),
        })
        await store.setRevisionState(rev.id, 'live')
        await store.setLiveRevision(agentApp.id, rev.id)
        // tools/list without a bearer token → RPC_UNAUTHORIZED (-32001).
        // The default app-build wires PUBLIC_ONLY_AUTH_PROVIDER, which
        // rejects every PAT, so any call to a PAT-mode agent fails here.
        const res = await request(app).post('/agents/gated/mcp').send({ jsonrpc: '2.0', id: 1, method: 'tools/list' })
        expect(res.body.error.code).toBe(-32001)
        // initialize is allowed pre-auth so a client can discover capabilities
        // before being asked to authenticate.
        const init = await request(app).post('/agents/gated/mcp').send({ jsonrpc: '2.0', id: 1, method: 'initialize' })
        expect(init.body.result.serverInfo.name).toBe('agent:gated')
    })

    it('GET /mcp/connect-info advertises a public agent with no headers', async () => {
        const { revisions, app } = mk()
        await seedApp(revisions, 'public-agent')
        const res = await request(app).get('/agents/public-agent/mcp/connect-info')
        expect(res.status).toBe(200)
        expect(res.body.url).toMatch(/\/agents\/public-agent\/mcp$/)
        expect(res.body.transport).toBe('http')
        expect(res.body.auth.mode).toBe('public')
        expect(res.body.auth.header).toBeNull()
        // No --header flags when no auth is required.
        expect(res.body.snippets.claude_code_command).not.toContain('--header')
        expect(res.body.snippets.mcp_json.mcpServers['public-agent'].headers).toBeUndefined()
    })

    it('GET /mcp/connect-info renders Bearer placeholder for a PAT-gated agent', async () => {
        const { revisions, app } = mk()
        const store = revisions
        const agentApp = await store.createApplication({
            team_id: 1,
            slug: 'pat-gated',
            name: 'pat-gated',
            description: '',
        })
        const rev = await store.createRevision({
            application_id: agentApp.id,
            parent_revision_id: null,
            created_by_id: null,
            bundle_uri: 's3://x/',
            spec: AgentSpecSchema.parse({
                model: 'x',
                triggers: [{ type: 'mcp', config: {} }],
                auth: { modes: [{ type: 'pat' }] },
            }),
        })
        await store.setRevisionState(rev.id, 'live')
        await store.setLiveRevision(agentApp.id, rev.id)
        const res = await request(app).get('/agents/pat-gated/mcp/connect-info')
        expect(res.body.auth.mode).toBe('pat')
        expect(res.body.auth.header).toBe('Authorization')
        // Placeholder only — never a real secret.
        expect(res.body.snippets.mcp_json.mcpServers['pat-gated'].headers.Authorization).toBe(
            'Bearer <YOUR_POSTHOG_PAT>'
        )
        expect(res.body.snippets.claude_code_command).toContain('Authorization=Bearer <YOUR_POSTHOG_PAT>')
    })

    it('GET /mcp/connect-info 404s when the agent has no mcp trigger', async () => {
        const { revisions, app } = mk()
        const store = revisions
        const agentApp = await store.createApplication({
            team_id: 1,
            slug: 'no-mcp',
            name: 'no-mcp',
            description: '',
        })
        const rev = await store.createRevision({
            application_id: agentApp.id,
            parent_revision_id: null,
            created_by_id: null,
            bundle_uri: 's3://x/',
            spec: AgentSpecSchema.parse({
                model: 'x',
                triggers: [{ type: 'chat', config: { require_auth: false } }],
            }),
        })
        await store.setRevisionState(rev.id, 'live')
        await store.setLiveRevision(agentApp.id, rev.id)
        const res = await request(app).get('/agents/no-mcp/mcp/connect-info')
        expect(res.status).toBe(404)
        expect(res.body.error).toBe('no_mcp_trigger')
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
