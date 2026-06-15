/**
 * Strict principal match on /send.
 *
 * `/run` captures the authenticated principal on the session. Subsequent
 * `/send` calls must carry a matching principal (same kind + identity).
 *
 * Old equivalent: isolated/strict-match.test.ts.
 */

import request from 'supertest'

import { AuthProvider, publicVerifier, readBearer } from '@posthog/agent-ingress'

import { buildCluster, closeSharedPool, Cluster, fauxText } from '../harness'

const PAT_A = 'phx_user_a'
const PAT_B = 'phx_user_b'

const provider: AuthProvider = {
    verifiers: [
        publicVerifier,
        {
            modeType: 'posthog',
            async verify(req, _mode, application) {
                const bearer = readBearer(req)
                if (!bearer) {
                    return { ok: false, status: 0, reason: 'skip' }
                }
                const userId = bearer === PAT_A ? 'pat-a' : bearer === PAT_B ? 'pat-b' : null
                if (!userId) {
                    return { ok: false, status: 401, reason: 'invalid_token' }
                }
                return {
                    ok: true,
                    principal: {
                        kind: 'posthog',
                        user_id: userId,
                        team_id: application.team_id,
                    },
                    credentials: { posthog_api: { kind: 'posthog_bearer', token: bearer } },
                }
            },
        },
    ],
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
        c.setScript([fauxText('ok?')])
        await c.deployAgent({ slug: 'p1', spec: { auth: { modes: [{ type: 'posthog' }] } } })
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

    it('pat agent: /send with a different PAT → 403 elevation_required', async () => {
        // B.1 v0: rejections on /send now follow the same `elevation_required`
        // surface as Slack thread bypass — the rejected message is preserved
        // as a PendingElevationRequest for replay-on-grant, the session is
        // not advanced, and the response carries an elevation_request_id.
        c.setScript([fauxText('ok?')])
        await c.deployAgent({ slug: 'p2', spec: { auth: { modes: [{ type: 'posthog' }] } } })
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
        expect(send.body.error).toBe('elevation_required')
        expect(send.body.elevation_request_id).toMatch(/.+/)
        expect(send.body.session_id).toBe(sid)

        const session = await c.queue.get(sid)
        expect(session!.pending_inputs).toHaveLength(0)
        expect(session!.pending_elevation_requests).toHaveLength(1)
        const requester = session!.pending_elevation_requests[0].requester
        expect(requester.kind === 'posthog' && requester.user_id).toBe('pat-b')
    })

    it('pat agent: /send with no auth → 401 (auth fails before strict-match)', async () => {
        c.setScript([fauxText('ok?')])
        await c.deployAgent({ slug: 'p3', spec: { auth: { modes: [{ type: 'posthog' }] } } })
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
        c.setScript([fauxText('ok?')])
        await c.deployAgent({
            slug: 'pub',
            spec: { auth: { modes: [{ type: 'public', acknowledge_public_exposure: true }] } },
        })
        const run = await request(c.ingress).post('/agents/pub/run').send({ message: 'hi' })
        const sid = run.body.session_id
        await c.drain()

        const send = await request(c.ingress).post('/agents/pub/send').send({ session_id: sid, message: 'still anon' })
        expect(send.status).toBe(200)
    })

    it('pat agent: /cancel enforces the session principal (owner 200, other 403, no-auth 401)', async () => {
        c.setScript([fauxText('ok?')])
        await c.deployAgent({ slug: 'cx', spec: { auth: { modes: [{ type: 'posthog' }] } } })
        const run = await request(c.ingress)
            .post('/agents/cx/run')
            .set('authorization', `Bearer ${PAT_A}`)
            .send({ message: 'hi' })
        const sid = run.body.session_id
        await c.drain()

        const noAuth = await request(c.ingress).post('/agents/cx/cancel').send({ session_id: sid })
        expect(noAuth.status).toBe(401)

        const otherUser = await request(c.ingress)
            .post('/agents/cx/cancel')
            .set('authorization', `Bearer ${PAT_B}`)
            .send({ session_id: sid })
        expect(otherUser.status).toBe(403)
        expect(otherUser.body.error).toBe('forbidden')

        // The session is untouched by the rejected cancels.
        expect((await c.queue.get(sid))!.state).not.toBe('cancelled')

        const owner = await request(c.ingress)
            .post('/agents/cx/cancel')
            .set('authorization', `Bearer ${PAT_A}`)
            .send({ session_id: sid })
        expect(owner.status).toBe(200)
    })

    it('pat agent: /client_tool_result enforces the session principal (owner 200, other 403, no-auth 401)', async () => {
        c.setScript([fauxText('ok?')])
        await c.deployAgent({ slug: 'ctr', spec: { auth: { modes: [{ type: 'posthog' }] } } })
        const run = await request(c.ingress)
            .post('/agents/ctr/run')
            .set('authorization', `Bearer ${PAT_A}`)
            .send({ message: 'hi' })
        const sid = run.body.session_id
        await c.drain()

        const body = { session_id: sid, call_id: 'call-1', result: { ok: true } }

        const noAuth = await request(c.ingress).post('/agents/ctr/client_tool_result').send(body)
        expect(noAuth.status).toBe(401)

        const otherUser = await request(c.ingress)
            .post('/agents/ctr/client_tool_result')
            .set('authorization', `Bearer ${PAT_B}`)
            .send(body)
        expect(otherUser.status).toBe(403)
        expect(otherUser.body.error).toBe('forbidden')

        const owner = await request(c.ingress)
            .post('/agents/ctr/client_tool_result')
            .set('authorization', `Bearer ${PAT_A}`)
            .send(body)
        expect(owner.status).toBe(200)
    })
})
