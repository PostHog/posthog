/**
 * Control-flow primitives after the session-restart redesign:
 *   - meta.ask_for_input    → completed (open); emits `ask_for_input` bus event
 *   - meta.end_turn         → completed (open)
 *   - meta.end_session      → closed (terminal unless `allow_restart`)
 *   - max_turns ceiling     → failed
 *   - upstream model error  → failed
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

    it('ask_for_input lands at completed (open) and emits a focus-hint event', async () => {
        c.setScript([fauxCallTool('@posthog/meta-ask-for-input', { prompt: 'continue?' })])
        await c.deployAgent({ slug: 'asker' })
        const res = await request(c.ingress).post('/agents/asker/run').send({ message: 'hi' })
        await c.drain()
        const session = await c.queue.get(res.body.session_id)
        expect(session!.state).toBe('completed')
        // The prompt is surfaced as a UI focus hint via the bus, not a parked state.
        const event = c.logs.forSession(res.body.session_id).find((e) => e.event === 'ask_for_input')
        expect(event).not.toBeUndefined()
    })

    it('end_session hard-closes the session', async () => {
        c.setScript([fauxCallTool('@posthog/meta-end-session', { summary: 'all done' })])
        await c.deployAgent({ slug: 'ender' })
        const res = await request(c.ingress).post('/agents/ender/run').send({ message: 'wrap' })
        await c.drain()
        const session = await c.queue.get(res.body.session_id)
        expect(session!.state).toBe('closed')
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
