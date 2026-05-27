/**
 * Trigger-level auth modes: public, pat, posthog_internal, shared_secret.
 *
 * Old equivalent: isolated/auth.test.ts (all 9 cases).
 */

import request from 'supertest'

import { AuthProvider } from '@posthog/agent-ingress-v2'

import { buildCluster, closeSharedPool, Cluster } from '../harness'

const KNOWN_PAT = 'phx_abc123def456'
const KNOWN_INTERNAL_SECRET = 'internal-secret-xyz'
const KNOWN_SHARED_SECRET = 'shared-secret-abc'

const provider: AuthProvider = {
    async verifyPat(token, application) {
        if (token === KNOWN_PAT) {
            return { kind: 'service', team_id: application.team_id, pat_id: 'pat-1' }
        }
        return null
    },
    async verifyInternal(secret, application) {
        if (secret === KNOWN_INTERNAL_SECRET) {
            return { kind: 'internal', team_id: application.team_id }
        }
        return null
    },
    async verifySharedSecret(secret, application) {
        if (secret === KNOWN_SHARED_SECRET) {
            return { kind: 'shared_secret', team_id: application.team_id }
        }
        return null
    },
}

describe('trigger auth: real e2e', () => {
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

    describe('public', () => {
        it('enqueues without auth, principal is anonymous', async () => {
            await c.deployAgent({ slug: 'pub', spec: { auth: { mode: 'public' } } })
            const res = await request(c.ingress).post('/agents/pub/run').send({ message: 'x' })
            expect(res.status).toBe(200)
            expect(res.body.principal).toEqual({ kind: 'anonymous' })
        })
    })

    describe('pat', () => {
        it('happy: valid bearer → 200 + service principal', async () => {
            await c.deployAgent({ slug: 'p1', spec: { auth: { mode: 'pat' } } })
            const res = await request(c.ingress)
                .post('/agents/p1/run')
                .set('authorization', `Bearer ${KNOWN_PAT}`)
                .send({ message: 'x' })
            expect(res.status).toBe(200)
            expect(res.body.principal.kind).toBe('service')
        })

        it('wrong token → 401', async () => {
            await c.deployAgent({ slug: 'p2', spec: { auth: { mode: 'pat' } } })
            const res = await request(c.ingress)
                .post('/agents/p2/run')
                .set('authorization', 'Bearer wrong-token')
                .send({ message: 'x' })
            expect(res.status).toBe(401)
        })

        it('missing header → 401', async () => {
            await c.deployAgent({ slug: 'p3', spec: { auth: { mode: 'pat' } } })
            const res = await request(c.ingress).post('/agents/p3/run').send({ message: 'x' })
            expect(res.status).toBe(401)
        })
    })

    describe('posthog_internal', () => {
        it('happy: matching internal header → 200 + internal principal', async () => {
            await c.deployAgent({ slug: 'i1', spec: { auth: { mode: 'posthog_internal' } } })
            const res = await request(c.ingress)
                .post('/agents/i1/run')
                .set('x-posthog-internal', KNOWN_INTERNAL_SECRET)
                .send({ message: 'x' })
            expect(res.status).toBe(200)
            expect(res.body.principal.kind).toBe('internal')
        })

        it('missing internal header → 403', async () => {
            await c.deployAgent({ slug: 'i2', spec: { auth: { mode: 'posthog_internal' } } })
            const res = await request(c.ingress).post('/agents/i2/run').send({ message: 'x' })
            expect(res.status).toBe(403)
        })

        it('wrong internal header value → 403', async () => {
            await c.deployAgent({ slug: 'i3', spec: { auth: { mode: 'posthog_internal' } } })
            const res = await request(c.ingress)
                .post('/agents/i3/run')
                .set('x-posthog-internal', 'wrong')
                .send({ message: 'x' })
            expect(res.status).toBe(403)
        })
    })

    describe('shared_secret', () => {
        it('happy: matching header value → 200 + shared_secret principal', async () => {
            await c.deployAgent({
                slug: 's1',
                spec: { auth: { mode: 'shared_secret', header: 'x-acme-secret' } },
            })
            const res = await request(c.ingress)
                .post('/agents/s1/run')
                .set('x-acme-secret', KNOWN_SHARED_SECRET)
                .send({ message: 'x' })
            expect(res.status).toBe(200)
            expect(res.body.principal.kind).toBe('shared_secret')
        })

        it('wrong header value → 401', async () => {
            await c.deployAgent({
                slug: 's2',
                spec: { auth: { mode: 'shared_secret', header: 'x-acme-secret' } },
            })
            const res = await request(c.ingress)
                .post('/agents/s2/run')
                .set('x-acme-secret', 'wrong')
                .send({ message: 'x' })
            expect(res.status).toBe(401)
        })

        it('missing header → 401', async () => {
            await c.deployAgent({
                slug: 's3',
                spec: { auth: { mode: 'shared_secret', header: 'x-acme-secret' } },
            })
            const res = await request(c.ingress).post('/agents/s3/run').send({ message: 'x' })
            expect(res.status).toBe(401)
        })
    })
})
