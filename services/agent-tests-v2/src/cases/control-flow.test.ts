/**
 * Control-flow primitives: meta.ask_for_input (→ waiting), meta.end_session
 * (→ completed with summary), max_turns ceiling (→ failed).
 *
 * Old equivalent surface:
 *   - greeting-bot's ask-then-greet (parking)
 *   - failure: upstream Anthropic error → failed (we emit via mock-error)
 */

import request from 'supertest'

import { buildCluster, closeSharedPool, Cluster } from '../harness'

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
        await c.deployAgent({ slug: 'asker', spec: { model: 'mock-ask' } })
        const res = await request(c.ingress).post('/agents/asker/run').send({ message: 'hi' })
        await c.drain()
        const session = await c.queue.get(res.body.session_id)
        expect(session!.state).toBe('waiting')
    })

    it("end_session completes the session with the model's summary", async () => {
        await c.deployAgent({ slug: 'ender', spec: { model: 'mock-end' } })
        const res = await request(c.ingress).post('/agents/ender/run').send({ message: 'wrap' })
        await c.drain()
        const session = await c.queue.get(res.body.session_id)
        expect(session!.state).toBe('completed')
    })

    it('max_turns ceiling marks the session failed', async () => {
        await c.deployAgent({
            slug: 'loopy',
            spec: {
                model: 'mock-loop',
                tools: [{ kind: 'native', id: 'posthog.query.v1' }],
                limits: { max_turns: 3, max_tool_calls: 100, max_wall_seconds: 60 },
            },
        })
        const res = await request(c.ingress).post('/agents/loopy/run').send({ message: 'go' })
        await c.drain()
        const session = await c.queue.get(res.body.session_id)
        expect(session!.state).toBe('failed')
    })

    it('upstream pi.dev error walks through to a failed session', async () => {
        await c.deployAgent({ slug: 'boom', spec: { model: 'mock-error:500' } })
        const res = await request(c.ingress).post('/agents/boom/run').send({ message: 'x' })
        await c.drain()
        const session = await c.queue.get(res.body.session_id)
        expect(session!.state).toBe('failed')
    })
})
