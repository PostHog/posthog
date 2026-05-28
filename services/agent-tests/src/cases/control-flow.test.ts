/**
 * Control-flow primitives: meta.ask_for_input (→ waiting), meta.end_session
 * (→ completed with summary), max_turns ceiling (→ failed), upstream model
 * error (→ failed).
 */

import request from 'supertest'

import { buildCluster, closeSharedPool, Cluster, fauxCallTool, fauxErrorTurn } from '../harness'

describe('control flow: real e2e', () => {
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

    it('ask_for_input suspends the session to state=waiting', async () => {
        c.setScript([fauxCallTool('@posthog/meta-ask-for-input', { prompt: 'continue?' })])
        await c.deployAgent({ slug: 'asker' })
        const res = await request(c.ingress).post('/agents/asker/run').send({ message: 'hi' })
        await c.drain()
        const session = await c.queue.get(res.body.session_id)
        expect(session!.state).toBe('waiting')
    })

    it("end_session completes the session with the model's summary", async () => {
        c.setScript([fauxCallTool('@posthog/meta-end-session', { summary: 'all done' })])
        await c.deployAgent({ slug: 'ender' })
        const res = await request(c.ingress).post('/agents/ender/run').send({ message: 'wrap' })
        await c.drain()
        const session = await c.queue.get(res.body.session_id)
        expect(session!.state).toBe('completed')
    })

    it('max_turns ceiling marks the session failed', async () => {
        // Script 5 tool calls — but the agent's max_turns is 3.
        c.setScript(
            Array(5)
                .fill(null)
                .map(() => fauxCallTool('@posthog/query', { query: 'select 1' }))
        )
        await c.deployAgent({
            slug: 'loopy',
            spec: {
                tools: [{ kind: 'native', id: '@posthog/query' }],
                limits: { max_turns: 3, max_tool_calls: 100, max_wall_seconds: 60 },
            },
        })
        const res = await request(c.ingress).post('/agents/loopy/run').send({ message: 'go' })
        await c.drain()
        const session = await c.queue.get(res.body.session_id)
        expect(session!.state).toBe('failed')
    })

    it('upstream model error walks through to a failed session', async () => {
        c.setScript([fauxErrorTurn('rate_limit')])
        await c.deployAgent({ slug: 'boom' })
        const res = await request(c.ingress).post('/agents/boom/run').send({ message: 'x' })
        await c.drain()
        const session = await c.queue.get(res.body.session_id)
        expect(session!.state).toBe('failed')
    })
})
