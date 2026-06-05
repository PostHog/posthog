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

    it('publishes assistant_text_delta events as the model streams', async () => {
        // v1 of streaming-and-reasoning.md — the runner consumes pi.stream()
        // and fans out per-token deltas to the SSE bus alongside the
        // existing full-text `assistant_text` event. The faux pi-ai client
        // emits one delta per word; consumers see them in order.
        c.setScript([fauxText('streaming reply text')])
        await c.deployAgent({ slug: 'ssee-stream' })
        const events: SessionEvent[] = []

        const run = await request(c.ingress).post('/agents/ssee-stream/run').send({ message: 'hi' })
        const sid = run.body.session_id
        const unsubscribe = c.bus.subscribe(sid, (e) => events.push(e))
        await c.drain()
        unsubscribe()

        const deltaTexts = events.filter((e) => e.kind === 'assistant_text_delta').map((e) => e.data.text as string)
        // pi-ai's faux provider chunks text on its own boundaries (not
        // necessarily word-aligned). The contract we assert is the contract
        // consumers actually need: at least one delta fires, and they
        // reconstruct the full text in order.
        expect(deltaTexts.length).toBeGreaterThan(0)
        expect(deltaTexts.join('')).toBe('streaming reply text')
        // The full-text assistant_text still fires at turn end — consumers
        // that don't care about deltas (KafkaLogSink, activity log) get one
        // event per turn the same as before.
        expect(events.some((e) => e.kind === 'assistant_text')).toBe(true)
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

    it('publishes user_message when /send drains a pending input into the next turn', async () => {
        // Live SSE consumers need the server-confirmed user message so the
        // optimistic local bubble can be reconciled against the actual
        // conversation order (rather than relying on a reload to ground
        // it via getSession).
        c.setScript([fauxText('first'), fauxText('second')])
        await c.deployAgent({ slug: 'ssee-user-msg' })

        const run = await request(c.ingress).post('/agents/ssee-user-msg/run').send({ message: 'hello' })
        const sid = run.body.session_id

        const events: SessionEvent[] = []
        const unsubscribe = c.bus.subscribe(sid, (e) => events.push(e))
        // Drain the first turn so the worker is idle before /send appends.
        await c.drain()
        await request(c.ingress).post('/agents/ssee-user-msg/send').send({ session_id: sid, message: 'follow-up' })
        await c.drain()
        unsubscribe()

        const userMessageEvts = events.filter((e) => e.kind === 'user_message')
        expect(userMessageEvts).toHaveLength(1)
        expect(userMessageEvts[0].data.text).toBe('follow-up')
    })

    it('publishes completed when the agent ends the turn with text', async () => {
        // Asking the user a question is no longer a dedicated bus event
        // — the agent just emits text and the turn ends.
        c.setScript([fauxText('continue?')])
        await c.deployAgent({ slug: 'ssee-3' })
        const events: SessionEvent[] = []
        const run = await request(c.ingress).post('/agents/ssee-3/run').send({ message: 'hi' })
        const sid = run.body.session_id

        const unsubscribe = c.bus.subscribe(sid, (e) => events.push(e))
        await c.drain()
        unsubscribe()

        const kinds = events.map((e) => e.kind)
        expect(kinds).toContain('completed')
        expect(kinds).not.toContain('ask_for_input')
    })

    it('GET /listen wires the SSE response headers and stays open', async () => {
        await c.deployAgent({ slug: 'ssee-4' })
        // Don't actually consume the stream — just verify the endpoint accepts
        // the request and replies with the SSE content-type. Force-disconnect
        // after a short delay so the test doesn't hang. `session_id` must be a
        // UUID for the zod-validated query schema; the value doesn't have to
        // match a real session — /listen just subscribes to the bus.
        const res = await request(c.ingress)
            .get('/agents/ssee-4/listen?session_id=00000000-0000-4000-8000-000000000001')
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
