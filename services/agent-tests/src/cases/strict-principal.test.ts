/**
 * Strict principal match on /send.
 *
 * `/run` captures the authenticated principal on the session. Subsequent
 * `/send` calls must carry a matching principal (same kind + identity).
 *
 * Old equivalent: isolated/strict-match.test.ts.
 */

import request from 'supertest'

import { AuthProvider } from '@posthog/agent-ingress'

import { buildCluster, closeSharedPool, Cluster, fauxCallTool } from '../harness'

const PAT_A = 'phx_user_a'
const PAT_B = 'phx_user_b'

const provider: AuthProvider = {
    async verifyPat(token, application) {
        if (token === PAT_A) {
            return { kind: 'service', team_id: application.team_id, pat_id: 'pat-a' }
        }
        if (token === PAT_B) {
            return { kind: 'service', team_id: application.team_id, pat_id: 'pat-b' }
        }
        return null
    },
    async verifyInternal() {
        return null
    },
    async verifySharedSecret() {
        return null
    },
}

describe('strict principal match on /send: real e2e', () => {
    let c: Cluster

    beforeEach(async () => {
        c = await buildCluster({ authProvider: provider })
    })

    afterEach(async () => {
        await c.teardown()
    })

    afterAll(async () => {
        await closeSharedPool()
    })

    it('pat agent: /send with the same PAT as /run → 200', async () => {
        c.setScript([fauxCallTool('@posthog/meta-ask-for-input', { prompt: 'ok?' })])
        await c.deployAgent({ slug: 'p1', spec: { auth: { mode: 'pat' } } })
        const run = await request(c.ingress)
            .post('/agents/p1/run')
            .set('authorization', `Bearer ${PAT_A}`)
            .send({ message: 'hi' })
        expect(run.status).toBe(200)
        const sid = run.body.session_id
        await c.drain()
        expect((await c.queue.get(sid))!.state).toBe('completed')

        const send = await request(c.ingress)
            .post('/agents/p1/send')
            .set('authorization', `Bearer ${PAT_A}`)
            .send({ session_id: sid, message: 'still me' })
        expect(send.status).toBe(200)
    })

    it('pat agent: /send with a different PAT → 403', async () => {
        c.setScript([fauxCallTool('@posthog/meta-ask-for-input', { prompt: 'ok?' })])
        await c.deployAgent({ slug: 'p2', spec: { auth: { mode: 'pat' } } })
        const run = await request(c.ingress)
            .post('/agents/p2/run')
            .set('authorization', `Bearer ${PAT_A}`)
            .send({ message: 'hi' })
        const sid = run.body.session_id
        await c.drain()

        // PAT_B is also valid auth but belongs to a different user.
        const send = await request(c.ingress)
            .post('/agents/p2/send')
            .set('authorization', `Bearer ${PAT_B}`)
            .send({ session_id: sid, message: 'other user' })
        expect(send.status).toBe(403)
        expect(send.body.error).toBe('principal_mismatch')
    })

    it('pat agent: /send with no auth → 401 (auth fails before strict-match)', async () => {
        c.setScript([fauxCallTool('@posthog/meta-ask-for-input', { prompt: 'ok?' })])
        await c.deployAgent({ slug: 'p3', spec: { auth: { mode: 'pat' } } })
        const run = await request(c.ingress)
            .post('/agents/p3/run')
            .set('authorization', `Bearer ${PAT_A}`)
            .send({ message: 'hi' })
        const sid = run.body.session_id
        await c.drain()

        const send = await request(c.ingress).post('/agents/p3/send').send({ session_id: sid, message: 'no auth' })
        expect(send.status).toBe(401)
    })

    it('public agent: /send without auth → 200 (both principals are anonymous)', async () => {
        c.setScript([fauxCallTool('@posthog/meta-ask-for-input', { prompt: 'ok?' })])
        await c.deployAgent({ slug: 'pub', spec: { auth: { mode: 'public' } } })
        const run = await request(c.ingress).post('/agents/pub/run').send({ message: 'hi' })
        const sid = run.body.session_id
        await c.drain()

        const send = await request(c.ingress).post('/agents/pub/send').send({ session_id: sid, message: 'still anon' })
        expect(send.status).toBe(200)
    })
})
