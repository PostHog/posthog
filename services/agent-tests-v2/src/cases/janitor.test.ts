/**
 * Janitor HTTP for Django: GET /sessions/:id, POST /sessions/:id/cancel, POST /sweep.
 *
 * Old equivalent: parts of isolated/cancel.test.ts + isolated/runtime.test.ts.
 */

import request from 'supertest'

import { buildCluster, closeSharedPool, Cluster } from '../harness'

describe('janitor: real e2e', () => {
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

    it('GET /sessions/:id returns full session JSON after a run', async () => {
        await c.deployAgent({ slug: 'j1', spec: { model: 'mock-echo' } })
        const create = await request(c.ingress).post('/agents/j1/run').send({ message: 'hi' })
        await c.drain()
        const res = await request(c.janitor).get(`/sessions/${create.body.session_id}`)
        expect(res.status).toBe(200)
        expect(res.body.state).toBe('completed')
        expect(res.body.conversation.length).toBeGreaterThanOrEqual(2)
    })

    it('404s for missing session id', async () => {
        const res = await request(c.janitor).get('/sessions/00000000-0000-0000-0000-000000000000')
        expect(res.status).toBe(404)
    })

    it('POST /sessions/:id/cancel marks failed', async () => {
        await c.deployAgent({ slug: 'j2', spec: { model: 'mock-ask' } })
        const create = await request(c.ingress).post('/agents/j2/run').send({ message: 'hi' })
        await c.drain()
        expect((await c.queue.get(create.body.session_id))!.state).toBe('waiting')
        const cancel = await request(c.janitor).post(`/sessions/${create.body.session_id}/cancel`)
        expect(cancel.status).toBe(200)
        expect((await c.queue.get(create.body.session_id))!.state).toBe('failed')
    })

    it('POST /sweep returns counts', async () => {
        const res = await request(c.janitor).post('/sweep')
        expect(res.status).toBe(200)
        expect(res.body).toEqual({ inspected: 0, reaped: 0, sessions: [] })
    })
})
