/**
 * Lifecycle edges on /send and /cancel.
 *
 * Old equivalent: persistent-chat/lifecycle-edges.test.ts.
 */

import request from 'supertest'

import { buildCluster, closeSharedPool, Cluster } from '../harness'

describe('session lifecycle edges: real e2e', () => {
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

    it('/send to a completed session → 410 Gone', async () => {
        await c.deployAgent({ slug: 'lc1', spec: { model: 'mock-echo' } })
        const create = await request(c.ingress).post('/agents/lc1/run').send({ message: 'first' })
        await c.drain()
        expect((await c.queue.get(create.body.session_id))!.state).toBe('completed')

        const send = await request(c.ingress)
            .post('/agents/lc1/send')
            .send({ session_id: create.body.session_id, message: 'second' })
        expect(send.status).toBe(410)
        expect(send.body.state).toBe('completed')
    })

    it('/send to a failed session → 410 Gone', async () => {
        await c.deployAgent({ slug: 'lc2', spec: { model: 'mock-error:500' } })
        const create = await request(c.ingress).post('/agents/lc2/run').send({ message: 'first' })
        await c.drain()
        expect((await c.queue.get(create.body.session_id))!.state).toBe('failed')
        const send = await request(c.ingress)
            .post('/agents/lc2/send')
            .send({ session_id: create.body.session_id, message: 'second' })
        expect(send.status).toBe(410)
    })

    it('/send to a nonexistent session id → 404', async () => {
        await c.deployAgent({ slug: 'lc3' })
        const res = await request(c.ingress)
            .post('/agents/lc3/send')
            .send({ session_id: '00000000-0000-0000-0000-000000000000', message: 'x' })
        expect(res.status).toBe(404)
    })

    it('/cancel of a parked (waiting) session → terminal failed', async () => {
        await c.deployAgent({ slug: 'cc1', spec: { model: 'mock-ask' } })
        const create = await request(c.ingress).post('/agents/cc1/run').send({ message: 'hi' })
        await c.drain()
        expect((await c.queue.get(create.body.session_id))!.state).toBe('waiting')
        const cancel = await request(c.ingress).post('/agents/cc1/cancel').send({ session_id: create.body.session_id })
        expect(cancel.status).toBe(200)
        expect((await c.queue.get(create.body.session_id))!.state).toBe('failed')
    })

    it('/cancel of a terminal (completed) session is idempotent', async () => {
        await c.deployAgent({ slug: 'cc2', spec: { model: 'mock-echo' } })
        const create = await request(c.ingress).post('/agents/cc2/run').send({ message: 'hi' })
        await c.drain()
        const cancel = await request(c.ingress).post('/agents/cc2/cancel').send({ session_id: create.body.session_id })
        expect(cancel.status).toBe(200)
        expect(cancel.body.idempotent).toBe(true)
        expect((await c.queue.get(create.body.session_id))!.state).toBe('completed') // unchanged
    })

    it('/cancel of a nonexistent session → 404', async () => {
        await c.deployAgent({ slug: 'cc3' })
        const res = await request(c.ingress)
            .post('/agents/cc3/cancel')
            .send({ session_id: '00000000-0000-0000-0000-000000000000' })
        expect(res.status).toBe(404)
    })
})
