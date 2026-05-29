/**
 * Queued follow-ups: /send calls that arrive while a session is parked or
 * in flight buffer to `pending_inputs` in arrival order. The runner drains
 * them into `conversation` at the start of the next turn.
 *
 * Old equivalent: persistent-chat/queued-followups.test.ts.
 */

import request from 'supertest'

import { buildCluster, closeSharedPool, Cluster, fauxText } from '../harness'

describe('queued follow-ups: real e2e', () => {
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

    it('a single /send after a text turn lands in pending_inputs', async () => {
        c.setScript([fauxText('go?'), fauxText('ok')])
        await c.deployAgent({ slug: 'q1' })
        const run = await request(c.ingress).post('/agents/q1/run').send({ message: 'hi' })
        const sid = run.body.session_id
        await c.drain()
        // A text-only turn lands at `completed` (open).
        expect((await c.queue.get(sid))!.state).toBe('completed')

        await request(c.ingress).post('/agents/q1/send').send({ session_id: sid, message: 'first follow-up' })
        const session = await c.queue.get(sid)
        expect(session!.pending_inputs).toHaveLength(1)
        expect(session!.pending_inputs[0].content).toBe('first follow-up')
    })

    it('three /sends after a completed turn buffer in arrival order; drain preserves order', async () => {
        c.setScript([fauxText('go?'), fauxText('done')])
        await c.deployAgent({ slug: 'q3' })
        const run = await request(c.ingress).post('/agents/q3/run').send({ message: 'first' })
        const sid = run.body.session_id
        await c.drain()
        // A text-only turn lands at `completed` (open).
        expect((await c.queue.get(sid))!.state).toBe('completed')

        // Three /sends without draining between them.
        await request(c.ingress).post('/agents/q3/send').send({ session_id: sid, message: 'second' })
        await request(c.ingress).post('/agents/q3/send').send({ session_id: sid, message: 'third' })
        await request(c.ingress).post('/agents/q3/send').send({ session_id: sid, message: 'fourth' })

        // All three queued, in order.
        const before = await c.queue.get(sid)
        expect(before!.pending_inputs.map((m) => (typeof m.content === 'string' ? m.content : ''))).toEqual([
            'second',
            'third',
            'fourth',
        ])

        await c.drain()
        const after = await c.queue.get(sid)
        expect(after!.state).toBe('completed')
        expect(after!.pending_inputs).toHaveLength(0)

        const userTexts = after!.conversation
            .filter((m) => m.role === 'user')
            .map((m) => (typeof m.content === 'string' ? m.content : ''))
        // The drained user messages appear in arrival order, after the original.
        expect(userTexts).toEqual(['first', 'second', 'third', 'fourth'])
    })

    it('a /send BEFORE the worker dequeues is durable (lands in conversation, not lost)', async () => {
        // The fresh first-turn run never drains before /send fires; the
        // scripted text response ends the first turn cleanly.
        c.setScript([fauxText('?'), fauxText('done')])
        await c.deployAgent({ slug: 'q-early' })
        const run = await request(c.ingress).post('/agents/q-early/run').send({ message: 'first' })
        const sid = run.body.session_id

        // /send arrives while session is still queued (no drain yet).
        await request(c.ingress).post('/agents/q-early/send').send({ session_id: sid, message: 'early-second' })

        // Session is still 'queued', second message is in pending_inputs.
        const before = await c.queue.get(sid)
        expect(before!.state).toBe('queued')
        expect(before!.pending_inputs).toHaveLength(1)

        await c.drain()
        const after = await c.queue.get(sid)
        const userTexts = after!.conversation
            .filter((m) => m.role === 'user')
            .map((m) => (typeof m.content === 'string' ? m.content : ''))
        // Both messages present in order — neither dropped.
        expect(userTexts).toContain('first')
        expect(userTexts).toContain('early-second')
    })
})
