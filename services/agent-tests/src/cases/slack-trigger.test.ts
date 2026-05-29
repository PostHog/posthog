/**
 * Slack trigger: real Slack event payloads → ingress → enqueue → runner.
 *
 * Old equivalent test surface:
 *   - persistent-chat/slack-thread-continuation.test.ts
 *   - isolated/slack-signature.test.ts
 *   - isolated/slack-identity.test.ts (partial — identity-space is v2 follow-up)
 *
 * Covers:
 *   - url_verification challenge round-trip
 *   - thread_ts dedupe: second mention in same thread resumes
 *   - distinct threads → distinct sessions
 *   - different user in same thread → elevation_required (B.1 v0 security fix
 *     — Slack thread replies must not advance a session opened by another user)
 *   - completed thread → fresh session
 *   - bot_id events ignored (no echo loop)
 *   - signature verification: missing, stale, wrong, valid
 */

import { createHmac } from 'crypto'
import request from 'supertest'

import { buildCluster, closeSharedPool, Cluster, fauxCallTool, fauxText } from '../harness'

function slackEvent(opts: {
    channel?: string
    user?: string
    text?: string
    ts?: string
    thread_ts?: string
    bot_id?: string
}): Record<string, unknown> {
    return {
        type: 'event_callback',
        event: {
            type: 'message',
            channel: opts.channel ?? 'C01',
            user: opts.user ?? 'U01',
            text: opts.text ?? 'hi',
            ts: opts.ts ?? '1.0',
            thread_ts: opts.thread_ts,
            bot_id: opts.bot_id,
        },
    }
}

function signSlack(body: string, secret: string, ts: number): { sig: string; tsString: string } {
    const tsString = String(ts)
    const base = `v0:${tsString}:${body}`
    const mac = createHmac('sha256', secret).update(base).digest('hex')
    return { sig: `v0=${mac}`, tsString }
}

describe('slack trigger: real e2e', () => {
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

    it('url_verification challenge round-trips', async () => {
        await c.deployAgent({ slug: 'echo' })
        const res = await request(c.ingress)
            .post('/agents/echo/slack/events')
            .send({ type: 'url_verification', challenge: 'xyz' })
        expect(res.status).toBe(200)
        expect(res.body.challenge).toBe('xyz')
    })

    it('thread_ts dedupe: second mention in same thread resumes existing session', async () => {
        c.setScript([fauxText('first reply'), fauxText('second reply')])
        await c.deployAgent({ slug: 'thready', spec: {} })
        const first = await request(c.ingress)
            .post('/agents/thready/slack/events')
            .send(slackEvent({ ts: '1', thread_ts: '1', text: 'first' }))
        expect(first.body.resumed).toBe(false)

        const second = await request(c.ingress)
            .post('/agents/thready/slack/events')
            .send(slackEvent({ ts: '2', thread_ts: '1', text: 'second' }))
        expect(second.body.resumed).toBe(true)
        expect(second.body.session_id).toBe(first.body.session_id)

        await c.drain()
        const session = await c.queue.get(first.body.session_id)
        // First message in conversation, second was queued into pending_inputs
        // and then drained by the next turn.
        const userMsgs = session!.conversation.filter((m) => m.role === 'user')
        expect(userMsgs.length).toBe(2)
    })

    it('different user in same thread → elevation_required, session is NOT advanced', async () => {
        // The Slack security gap (B.1 v0): before this fix, any Slack user
        // who could post in a thread could resume someone else's session by
        // virtue of thread_ts/externalKey matching. Now the second user's
        // message is rejected, recorded as a PendingElevationRequest, and
        // the session stays parked until the owner grants elevation.
        c.setScript([fauxText('first reply')])
        await c.deployAgent({ slug: 'gated', spec: {} })
        const first = await request(c.ingress)
            .post('/agents/gated/slack/events')
            .send(slackEvent({ user: 'U-ALICE', ts: '1', thread_ts: '1', text: 'alice opens' }))
        expect(first.body.resumed).toBe(false)
        await c.drain()

        const second = await request(c.ingress)
            .post('/agents/gated/slack/events')
            .send(slackEvent({ user: 'U-BOB', ts: '2', thread_ts: '1', text: 'bob barges in' }))
        // Slack expects 200 on events; the elevation is signalled in the body.
        expect(second.status).toBe(200)
        expect(second.body.elevation_required).toBe(true)
        expect(second.body.session_id).toBe(first.body.session_id)
        expect(second.body.resumed).toBe(false)
        expect(second.body.elevation_request_id).toMatch(/.+/)

        const session = await c.queue.get(first.body.session_id)
        // Bob's message must NOT be visible to the runner.
        expect(session!.pending_inputs).toHaveLength(0)
        const userMsgs = session!.conversation.filter((m) => m.role === 'user')
        expect(userMsgs.map((m) => m.content)).toEqual(['alice opens'])
        // It IS preserved on the elevation request so a future grant can replay.
        expect(session!.pending_elevation_requests).toHaveLength(1)
        expect(session!.pending_elevation_requests[0].state).toBe('pending')
        expect(session!.pending_elevation_requests[0].trigger).toBe('slack')
    })

    describe('slack interactivity: elevation grant / decline', () => {
        // The button `value` shape the ingress encodes/decodes — keep in sync
        // with `encodeElevationActionValue` in services/agent-ingress/src/triggers/slack.ts.
        function buildPayload(opts: {
            sessionId: string
            requestId: string
            decision: 'grant' | 'decline'
            user: string
            workspaceId?: string
        }): string {
            return JSON.stringify({
                type: 'block_actions',
                team: { id: opts.workspaceId ?? 'unknown' },
                user: { id: opts.user },
                actions: [
                    {
                        action_id: 'elevation_decision',
                        value: `elevation:${opts.decision}:${opts.sessionId}:${opts.requestId}`,
                    },
                ],
            })
        }

        async function setupRejectedRequest(slug: string): Promise<{ sessionId: string; requestId: string }> {
            c.setScript([fauxText('first reply'), fauxText('after grant')])
            await c.deployAgent({ slug, spec: {} })
            const first = await request(c.ingress)
                .post(`/agents/${slug}/slack/events`)
                .send(slackEvent({ user: 'U-ALICE', ts: '1', thread_ts: '1', text: 'alice opens' }))
            await c.drain()
            const bob = await request(c.ingress)
                .post(`/agents/${slug}/slack/events`)
                .send(slackEvent({ user: 'U-BOB', ts: '2', thread_ts: '1', text: 'bob barges in' }))
            return { sessionId: first.body.session_id, requestId: bob.body.elevation_request_id }
        }

        it('owner grant: ACL entry written, bob message replays, session re-queues', async () => {
            const { sessionId, requestId } = await setupRejectedRequest('gated-grant')

            const grant = await request(c.ingress)
                .post('/agents/gated-grant/slack/interactivity')
                .send({
                    payload: buildPayload({
                        sessionId,
                        requestId,
                        decision: 'grant',
                        user: 'U-ALICE',
                    }),
                })
            expect(grant.status).toBe(200)
            expect(grant.body.text).toMatch(/granted/i)

            // Drain a turn so the runner picks up bob's now-replayed message.
            await c.drain()
            const session = await c.queue.get(sessionId)
            expect(session!.acl).toHaveLength(1)
            expect(session!.acl[0].state).toBe('active')
            expect(session!.pending_elevation_requests[0].state).toBe('granted')
            // Conversation now reflects bob's message being delivered.
            const userMsgs = session!.conversation.filter((m) => m.role === 'user')
            expect(userMsgs.map((m) => m.content)).toEqual(['alice opens', 'bob barges in'])
        })

        it('non-owner click: ephemeral message, request stays pending', async () => {
            const { sessionId, requestId } = await setupRejectedRequest('gated-noowner')

            const stranger = await request(c.ingress)
                .post('/agents/gated-noowner/slack/interactivity')
                .send({
                    payload: buildPayload({
                        sessionId,
                        requestId,
                        decision: 'grant',
                        user: 'U-CAROL',
                    }),
                })
            expect(stranger.status).toBe(200)
            expect(stranger.body.response_type).toBe('ephemeral')
            expect(stranger.body.text).toMatch(/only the session owner/i)

            const session = await c.queue.get(sessionId)
            expect(session!.acl).toHaveLength(0)
            expect(session!.pending_elevation_requests[0].state).toBe('pending')
        })

        it('decline: marks request declined, does not advance the session', async () => {
            const { sessionId, requestId } = await setupRejectedRequest('gated-decline')

            const decline = await request(c.ingress)
                .post('/agents/gated-decline/slack/interactivity')
                .send({
                    payload: buildPayload({
                        sessionId,
                        requestId,
                        decision: 'decline',
                        user: 'U-ALICE',
                    }),
                })
            expect(decline.status).toBe(200)
            expect(decline.body.text).toMatch(/declined/i)

            const session = await c.queue.get(sessionId)
            expect(session!.acl).toHaveLength(0)
            expect(session!.pending_inputs).toHaveLength(0)
            expect(session!.pending_elevation_requests[0].state).toBe('declined')
        })

        it('replaying a grant on an already-decided request returns "already decided"', async () => {
            const { sessionId, requestId } = await setupRejectedRequest('gated-replay')

            const first = await request(c.ingress)
                .post('/agents/gated-replay/slack/interactivity')
                .send({
                    payload: buildPayload({
                        sessionId,
                        requestId,
                        decision: 'grant',
                        user: 'U-ALICE',
                    }),
                })
            expect(first.status).toBe(200)
            await c.drain()

            const second = await request(c.ingress)
                .post('/agents/gated-replay/slack/interactivity')
                .send({
                    payload: buildPayload({
                        sessionId,
                        requestId,
                        decision: 'grant',
                        user: 'U-ALICE',
                    }),
                })
            expect(second.status).toBe(200)
            expect(second.body.response_type).toBe('ephemeral')
            expect(second.body.text).toMatch(/already been decided/i)
        })

        it('missing payload returns 400', async () => {
            await c.deployAgent({ slug: 'gated-bad', spec: {} })
            const res = await request(c.ingress).post('/agents/gated-bad/slack/interactivity').send({})
            expect(res.status).toBe(400)
            expect(res.body.error).toBe('missing_payload')
        })

        it('unknown session id returns 404', async () => {
            await c.deployAgent({ slug: 'gated-missing', spec: {} })
            const res = await request(c.ingress)
                .post('/agents/gated-missing/slack/interactivity')
                .send({
                    payload: buildPayload({
                        sessionId: '00000000-0000-0000-0000-000000000000',
                        requestId: 'fake',
                        decision: 'grant',
                        user: 'U-ALICE',
                    }),
                })
            expect(res.status).toBe(404)
            expect(res.body.error).toBe('session_not_found')
        })
    })

    it('distinct threads create distinct sessions', async () => {
        await c.deployAgent({ slug: 'distinct', spec: {} })
        const a = await request(c.ingress)
            .post('/agents/distinct/slack/events')
            .send(slackEvent({ ts: '1', thread_ts: '1', text: 'thread a' }))
        const b = await request(c.ingress)
            .post('/agents/distinct/slack/events')
            .send(slackEvent({ ts: '2', thread_ts: '2', text: 'thread b' }))
        expect(a.body.session_id).not.toBe(b.body.session_id)
    })

    it('bot_id events are ignored (no echo loop)', async () => {
        await c.deployAgent({ slug: 'noloop' })
        const res = await request(c.ingress)
            .post('/agents/noloop/slack/events')
            .send(slackEvent({ bot_id: 'B01', text: 'I am a bot' }))
        expect(res.status).toBe(200)
        expect(res.body.session_id).toBeUndefined()
    })

    it('idle `completed` (open) thread is resumed on the next mention', async () => {
        // Under the new state machine `completed` is open by default —
        // external_key reuse picks it back up. Only `closed` (via
        // meta-end-session) or `failed` forces a fresh session.
        c.setScript([fauxText('done'), fauxText('again')])
        await c.deployAgent({ slug: 'freshish', spec: {} })
        const first = await request(c.ingress)
            .post('/agents/freshish/slack/events')
            .send(slackEvent({ ts: '1', thread_ts: '1', text: 'first' }))
        await c.drain()
        expect((await c.queue.get(first.body.session_id))!.state).toBe('completed')

        const second = await request(c.ingress)
            .post('/agents/freshish/slack/events')
            .send(slackEvent({ ts: '2', thread_ts: '1', text: 'second' }))
        // Same external_key, session is open → resumed.
        expect(second.body.resumed).toBe(true)
        expect(second.body.session_id).toBe(first.body.session_id)
    })

    it('`closed` thread starts a fresh session on the next mention', async () => {
        c.setScript([fauxCallTool('@posthog/meta-end-session', { summary: 'done' }), fauxText('again')])
        await c.deployAgent({ slug: 'freshish-closed', spec: {} })
        const first = await request(c.ingress)
            .post('/agents/freshish-closed/slack/events')
            .send(slackEvent({ ts: '1', thread_ts: '1', text: 'first' }))
        await c.drain()
        expect((await c.queue.get(first.body.session_id))!.state).toBe('closed')

        const second = await request(c.ingress)
            .post('/agents/freshish-closed/slack/events')
            .send(slackEvent({ ts: '2', thread_ts: '1', text: 'second' }))
        // Closed session is terminal → fresh session.
        expect(second.body.resumed).toBe(false)
        expect(second.body.session_id).not.toBe(first.body.session_id)
    })

    describe('signature verification', () => {
        const secret = 'test-slack-secret'

        async function withSigCluster(): Promise<Cluster> {
            const cluster = await buildCluster({ slackSigningSecret: secret })
            await cluster.deployAgent({ slug: 'signed' })
            return cluster
        }

        it('missing signature → 401', async () => {
            const cc = await withSigCluster()
            try {
                const res = await request(cc.ingress)
                    .post('/agents/signed/slack/events')
                    .set('x-slack-request-timestamp', String(Math.floor(Date.now() / 1000)))
                    .send(slackEvent({}))
                expect(res.status).toBe(401)
            } finally {
                await cc.teardown()
            }
        })

        it('stale timestamp (>5 min) → 401 (replay protection)', async () => {
            const cc = await withSigCluster()
            try {
                const stale = Math.floor(Date.now() / 1000) - 10 * 60
                const body = JSON.stringify(slackEvent({}))
                const { sig } = signSlack(body, secret, stale)
                const res = await request(cc.ingress)
                    .post('/agents/signed/slack/events')
                    .set('content-type', 'application/json')
                    .set('x-slack-request-timestamp', String(stale))
                    .set('x-slack-signature', sig)
                    .send(body)
                expect(res.status).toBe(401)
            } finally {
                await cc.teardown()
            }
        })

        it('signature signed with wrong secret → 401', async () => {
            const cc = await withSigCluster()
            try {
                const now = Math.floor(Date.now() / 1000)
                const body = JSON.stringify(slackEvent({}))
                const { sig } = signSlack(body, 'wrong-secret', now)
                const res = await request(cc.ingress)
                    .post('/agents/signed/slack/events')
                    .set('content-type', 'application/json')
                    .set('x-slack-request-timestamp', String(now))
                    .set('x-slack-signature', sig)
                    .send(body)
                expect(res.status).toBe(401)
            } finally {
                await cc.teardown()
            }
        })

        it('valid signature → 200', async () => {
            const cc = await withSigCluster()
            try {
                const now = Math.floor(Date.now() / 1000)
                const body = JSON.stringify({ type: 'url_verification', challenge: 'xyz' })
                const { sig } = signSlack(body, secret, now)
                const res = await request(cc.ingress)
                    .post('/agents/signed/slack/events')
                    .set('content-type', 'application/json')
                    .set('x-slack-request-timestamp', String(now))
                    .set('x-slack-signature', sig)
                    .send(body)
                expect(res.status).toBe(200)
                expect(res.body.challenge).toBe('xyz')
            } finally {
                await cc.teardown()
            }
        })
    })
})
