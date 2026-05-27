/**
 * Webhook + per-agent MCP triggers.
 *
 * Old equivalent: webhook is new in v2 (was a generic public agent before),
 * MCP transport is new (per-agent MCP exposure).
 */

import request from 'supertest'

import { buildCluster, closeSharedPool, Cluster } from '../harness'

describe('webhook trigger: real e2e', () => {
    let c: Cluster

    beforeEach(async () => {
        c = await buildCluster()
    })

    afterEach(async () => {
        await c.teardown()
    })

    afterAll(async () => {
        await closeSharedPool()
    })

    it('creates a session with the JSON body as content', async () => {
        await c.deployAgent({ slug: 'wh', spec: { model: 'mock-echo' } })
        const res = await request(c.ingress)
            .post('/agents/wh/webhook')
            .send({ payload: { account: 'acme' } })
        expect(res.status).toBe(200)
        await c.drain()
        const session = await c.queue.get(res.body.session_id)
        expect(session!.state).toBe('completed')
        expect(session!.conversation[0].content).toBe(JSON.stringify({ payload: { account: 'acme' } }))
    })

    it('x-external-key header is used for dedupe', async () => {
        await c.deployAgent({ slug: 'wh2', spec: { model: 'mock-echo' } })
        const a = await request(c.ingress).post('/agents/wh2/webhook').set('x-external-key', 'k-1').send({ a: 1 })
        const b = await request(c.ingress).post('/agents/wh2/webhook').set('x-external-key', 'k-1').send({ a: 2 })
        // First creates fresh, second resumes (since first is still queued/running)
        expect(a.body.resumed).toBe(false)
        expect(b.body.resumed).toBe(true)
        expect(b.body.session_id).toBe(a.body.session_id)
    })

    it('404s an unknown agent slug', async () => {
        const res = await request(c.ingress).post('/agents/ghost/webhook').send({})
        expect(res.status).toBe(404)
    })
})

describe('per-agent MCP transport: real e2e', () => {
    let c: Cluster

    beforeEach(async () => {
        c = await buildCluster()
    })

    afterEach(async () => {
        await c.teardown()
    })

    afterAll(async () => {
        await closeSharedPool()
    })

    it('initialize returns server info with slug + revision id', async () => {
        await c.deployAgent({ slug: 'mcp-bot' })
        const res = await request(c.ingress)
            .post('/agents/mcp-bot/mcp')
            .send({ jsonrpc: '2.0', id: 1, method: 'initialize' })
        expect(res.body.result.serverInfo.name).toBe('agent:mcp-bot')
        expect(res.body.result.serverInfo.version).not.toBeUndefined()
        expect(res.body.result.protocolVersion).not.toBeUndefined()
    })

    it("tools/list returns the agent's chat tool", async () => {
        await c.deployAgent({ slug: 'lst' })
        const res = await request(c.ingress)
            .post('/agents/lst/mcp')
            .send({ jsonrpc: '2.0', id: 1, method: 'tools/list' })
        expect(res.body.result.tools).toHaveLength(1)
        expect(res.body.result.tools[0].name).toBe('chat')
        expect(res.body.result.tools[0].inputSchema.required).toContain('message')
    })

    it('tools/call name=chat enqueues a session and returns its id', async () => {
        await c.deployAgent({ slug: 'callee', spec: { model: 'mock-echo' } })
        const res = await request(c.ingress)
            .post('/agents/callee/mcp')
            .send({
                jsonrpc: '2.0',
                id: 2,
                method: 'tools/call',
                params: { name: 'chat', arguments: { message: 'via mcp' } },
            })
        const text = res.body.result.content[0].text
        const parsed = JSON.parse(text) as { session_id: string }
        expect(parsed.session_id).not.toBeUndefined()
        await c.drain()
        const session = await c.queue.get(parsed.session_id)
        expect(session!.state).toBe('completed')
        expect(session!.conversation[0].content).toBe('via mcp')
    })

    it('tools/call with unknown tool returns JSON-RPC error', async () => {
        await c.deployAgent({ slug: 'ut' })
        const res = await request(c.ingress)
            .post('/agents/ut/mcp')
            .send({
                jsonrpc: '2.0',
                id: 3,
                method: 'tools/call',
                params: { name: 'nope', arguments: {} },
            })
        expect(res.body.error).not.toBeUndefined()
        expect(res.body.error.code).toBe(-32601)
    })

    it('unknown JSON-RPC method returns error', async () => {
        await c.deployAgent({ slug: 'uk' })
        const res = await request(c.ingress).post('/agents/uk/mcp').send({ jsonrpc: '2.0', id: 4, method: 'nope/here' })
        expect(res.body.error).not.toBeUndefined()
    })
})
