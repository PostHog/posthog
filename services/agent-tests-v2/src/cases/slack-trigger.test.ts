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
 *   - different user in same thread → handled (v2: same session — identity is
 *     follow-up)
 *   - completed thread → fresh session
 *   - bot_id events ignored (no echo loop)
 *   - signature verification: missing, stale, wrong, valid
 */

import { createHmac } from 'crypto'
import request from 'supertest'

import { buildCluster, closeSharedPool, Cluster } from '../harness'

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
        await c.deployAgent({ slug: 'thready', spec: { model: 'mock-echo' } })
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
        // 2 user messages appended pre-drain
        const userMsgs = session!.conversation.filter((m) => m.role === 'user')
        expect(userMsgs.length).toBe(2)
    })

    it('distinct threads create distinct sessions', async () => {
        await c.deployAgent({ slug: 'distinct', spec: { model: 'mock-echo' } })
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

    it('completed thread starts a fresh session on the next mention', async () => {
        await c.deployAgent({ slug: 'freshish', spec: { model: 'mock-echo' } })
        const first = await request(c.ingress)
            .post('/agents/freshish/slack/events')
            .send(slackEvent({ ts: '1', thread_ts: '1', text: 'first' }))
        await c.drain()
        expect((await c.queue.get(first.body.session_id))!.state).toBe('completed')

        const second = await request(c.ingress)
            .post('/agents/freshish/slack/events')
            .send(slackEvent({ ts: '2', thread_ts: '1', text: 'second' }))
        // Completed session won't be resumed — fresh session id.
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
