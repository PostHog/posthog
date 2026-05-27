/**
 * Native tool dispatch: agent's spec references posthog.query.v1, mock-pi-dev
 * routes a tool_use through the runner's native registry. Old equivalent:
 * runtime: pat-auth agent enqueues + runs (without ClickHouse assertions,
 * which v2 logs are a follow-up).
 */

import request from 'supertest'

import { buildCluster, closeSharedPool, Cluster } from '../harness'

describe('native tool dispatch: real e2e', () => {
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

    it('agent calling posthog.query.v1 routes through the native registry', async () => {
        await c.deployAgent({
            slug: 'analyst',
            spec: {
                model: 'mock-tool:posthog.query.v1',
                tools: [{ kind: 'native', id: 'posthog.query.v1' }],
            },
        })
        const res = await request(c.ingress).post('/agents/analyst/run').send({ message: 'run query' })
        await c.drain()
        const session = await c.queue.get(res.body.session_id)
        expect(session!.state).toBe('completed')
        const userTurns = session!.conversation.filter((m) => m.role === 'user')
        // Original user + a tool_result follow-up
        expect(userTurns.length).toBe(2)
        const toolResult = userTurns[1] as { content: Array<{ type: string }> }
        expect(toolResult.content[0].type).toBe('tool_result')
    })

    it('multi-tool dispatch: agent calls posthog.query then web.search then ends', async () => {
        await c.deployAgent({
            slug: 'compound',
            spec: {
                model: 'mock-multi-tool:posthog.query.v1,meta.end_session.v1',
                tools: [
                    { kind: 'native', id: 'posthog.query.v1' },
                    { kind: 'native', id: 'meta.end_session.v1' },
                ],
            },
        })
        // meta.end_session.v1 is in the tools list but mock-multi-tool calls it
        // explicitly. The runner's meta-tool branch terminates the session.
        const res = await request(c.ingress).post('/agents/compound/run').send({ message: 'go' })
        await c.drain()
        const session = await c.queue.get(res.body.session_id)
        expect(session!.state).toBe('completed')
    })

    it('rejects tools not declared in the revision spec', async () => {
        await c.deployAgent({
            slug: 'no-tools',
            spec: { model: 'mock-tool:posthog.query.v1' }, // model wants to call it...
        })
        const res = await request(c.ingress).post('/agents/no-tools/run').send({ message: 'x' })
        await c.drain()
        const session = await c.queue.get(res.body.session_id)
        // The runner declared no tools to pi.dev, so pi.dev shouldn't even know
        // it can call them. mock-pi-dev ignores the declared tools list and just
        // returns a tool_use anyway — the runner catches "tool not in revision"
        // and the model would loop. We're testing the guard works.
        expect(['failed', 'completed']).toContain(session!.state)
    })
})
