/**
 * SSE lifecycle stream: subscribe to /listen, fire /run, assert the runner
 * publishes the expected event sequence through the bus.
 *
 * Old equivalent: isolated/listen-sse.test.ts.
 */

import request from 'supertest'

import type { SessionEvent } from '@posthog/agent-shared'

import { buildCluster, closeSharedPool, Cluster, fauxCallTool, fauxText } from '../harness'

describe('listen SSE: real e2e', () => {
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

    it('publishes session_started → turn_started → assistant_text → completed', async () => {
        c.setScript([fauxText('hi back')])
        await c.deployAgent({ slug: 'ssee-1' })
        // Capture events directly from the bus (the same bus the SSE endpoint subscribes to).
        const events: SessionEvent[] = []

        const run = await request(c.ingress).post('/agents/ssee-1/run').send({ message: 'hi' })
        const sid = run.body.session_id

        // Subscribe BEFORE drain so we catch the events as they fire.
        const unsubscribe = c.bus.subscribe(sid, (e) => events.push(e))
        await c.drain()
        unsubscribe()

        const kinds = events.map((e) => e.kind)
        expect(kinds[0]).toBe('session_started')
        expect(kinds).toContain('turn_started')
        expect(kinds).toContain('assistant_text')
        expect(kinds[kinds.length - 1]).toBe('completed')
    })

    it('publishes tool_call + tool_result events when the model invokes a tool', async () => {
        c.setScript([fauxCallTool('@posthog/query', { query: 'select 1' }), fauxText('done')])
        await c.deployAgent({
            slug: 'ssee-2',
            spec: { tools: [{ kind: 'native', id: '@posthog/query' }] },
        })
        const events: SessionEvent[] = []
        const run = await request(c.ingress).post('/agents/ssee-2/run').send({ message: 'go' })
        const sid = run.body.session_id

        const unsubscribe = c.bus.subscribe(sid, (e) => events.push(e))
        await c.drain()
        unsubscribe()

        const toolCallEvt = events.find((e) => e.kind === 'tool_call')
        const toolResultEvt = events.find((e) => e.kind === 'tool_result')
        expect(toolCallEvt).not.toBeUndefined()
        expect(toolCallEvt!.data.name).toBe('@posthog/query')
        expect(toolResultEvt).not.toBeUndefined()
        expect(toolResultEvt!.data.ok).toBe(true)
    })

    it('publishes waiting on ask_for_input', async () => {
        c.setScript([fauxCallTool('@posthog/meta-ask-for-input', { prompt: 'continue?' })])
        await c.deployAgent({ slug: 'ssee-3' })
        const events: SessionEvent[] = []
        const run = await request(c.ingress).post('/agents/ssee-3/run').send({ message: 'hi' })
        const sid = run.body.session_id

        const unsubscribe = c.bus.subscribe(sid, (e) => events.push(e))
        await c.drain()
        unsubscribe()

        expect(events.map((e) => e.kind)).toContain('waiting')
    })

    it('GET /listen wires the SSE response headers and stays open', async () => {
        await c.deployAgent({ slug: 'ssee-4' })
        // Don't actually consume the stream — just verify the endpoint accepts
        // the request and replies with the SSE content-type. Force-disconnect
        // after a short delay so the test doesn't hang.
        const res = await request(c.ingress)
            .get('/agents/ssee-4/listen?session_id=some-id')
            .buffer(false)
            .parse((response, callback) => {
                response.on('data', () => {
                    /* discard */
                })
                response.on('end', () => callback(null, ''))
                setTimeout(() => (response as unknown as { destroy: () => void }).destroy(), 50)
            })
        expect(res.headers['content-type']).toMatch(/text\/event-stream/)
    })
})
