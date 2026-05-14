import supertest from 'supertest'
import type { Express } from 'ultimate-express'

import { InMemorySessionBus, ResolvedRevision, SessionInputMessage } from '@posthog/agent-core'

import { RevisionResolver } from './resolver'
import { ServerDeps, buildServer } from './server'

class FakeQueue {
    public created: Array<Record<string, unknown>> = []
    private idCounter = 0
    async createJob(input: Record<string, unknown>): Promise<string> {
        this.created.push(input)
        this.idCounter += 1
        return `session-${this.idCounter}`
    }
}

function makeRevision(overrides: Partial<ResolvedRevision> = {}): ResolvedRevision {
    return {
        applicationId: 'b1f3d6e4-4c2a-4b0e-9d5a-1c9f7e1d8a01',
        applicationSlug: 'analytics-bot',
        teamId: 7,
        revisionId: 'b1f3d6e4-4c2a-4b0e-9d5a-1c9f7e1d8a02',
        revisionState: 'ready',
        bundleS3Key: 's3://bundles/abc',
        bundleSha256: 'abcd',
        topLevelConfig: {},
        parsedManifest: null,
        auth: { mode: 'public' },
        ...overrides,
    }
}

function makeResolver(revision: ResolvedRevision | null): RevisionResolver {
    return {
        resolveDomain: async () => revision,
        resolveApplication: async () => revision,
        invalidate: () => undefined,
    } as unknown as RevisionResolver
}

interface TestHarness {
    queue: FakeQueue
    bus: InMemorySessionBus
    app: Express
    teardown: () => Promise<void>
}

/**
 * Mirrors the pattern in nodejs/src/api/router.test.ts: bind the ultimate-express app to
 * an ephemeral port first, then hand the app to supertest (which uses `app.address()`).
 */
async function startServer(overrides: Partial<ServerDeps> = {}): Promise<TestHarness> {
    const queue = new FakeQueue()
    const bus = new InMemorySessionBus()
    const resolver = makeResolver(makeRevision())
    const deps: ServerDeps = {
        queue: queue as unknown as ServerDeps['queue'],
        bus,
        resolver,
        domainSuffix: '.agents.posthog.com',
        ...overrides,
    }
    const app = buildServer(deps)
    await new Promise<void>((resolve, reject) => {
        try {
            app.listen(0, () => resolve())
        } catch (err) {
            reject(err)
        }
    })
    return {
        queue,
        bus,
        app,
        teardown: async () => {
            await bus.disconnect()
        },
    }
}

describe('agent-ingress server', () => {
    let harness: TestHarness

    afterEach(async () => {
        await harness.teardown()
    })

    it('GET /health returns ok', async () => {
        harness = await startServer()
        const res = await supertest(harness.app).get('/health')
        expect(res.status).toBe(200)
        expect(res.body).toEqual({ ok: true })
    })

    it('GET /status returns service identity', async () => {
        harness = await startServer()
        const res = await supertest(harness.app).get('/status')
        expect(res.status).toBe(200)
        expect(res.body.service).toBe('agent-ingress')
        expect(typeof res.body.uptimeSeconds).toBe('number')
    })

    it('POST /run enqueues a session when revision is ready', async () => {
        harness = await startServer()
        const res = await supertest(harness.app)
            .post('/run')
            .set('x-original-host', 'analytics-bot.agents.posthog.com')
            .send({ input: { foo: 'bar' } })
        expect(res.status).toBe(202)
        expect(res.body.sessionId).toBe('session-1')
        expect(harness.queue.created).toHaveLength(1)
        expect(harness.queue.created[0]).toMatchObject({
            teamId: 7,
            applicationId: 'b1f3d6e4-4c2a-4b0e-9d5a-1c9f7e1d8a01',
            revisionId: 'b1f3d6e4-4c2a-4b0e-9d5a-1c9f7e1d8a02',
            queueName: 'default',
        })
    })

    it('POST /run rejects non-ready revisions', async () => {
        const resolver = makeResolver(makeRevision({ revisionState: 'uploaded' }))
        harness = await startServer({ resolver })
        const res = await supertest(harness.app)
            .post('/run')
            .set('x-original-host', 'analytics-bot.agents.posthog.com')
            .send({})
        expect(res.status).toBe(409)
    })

    it('POST /run 404s when no application matches the host', async () => {
        const resolver = makeResolver(null)
        harness = await startServer({ resolver })
        const res = await supertest(harness.app)
            .post('/run')
            .set('x-original-host', 'unknown.agents.posthog.com')
            .send({})
        expect(res.status).toBe(404)
    })

    it('POST /run rejects hosts that do not match the suffix', async () => {
        harness = await startServer()
        const res = await supertest(harness.app).post('/run').set('x-original-host', 'evil.example.com').send({})
        expect(res.status).toBe(400)
    })

    it('POST /run rejects shared_secret requests with no bearer token', async () => {
        const resolver = makeResolver(makeRevision({ auth: { mode: 'shared_secret', token: 'sekret' } }))
        harness = await startServer({ resolver })
        const res = await supertest(harness.app)
            .post('/run')
            .set('x-original-host', 'analytics-bot.agents.posthog.com')
            .send({})
        expect(res.status).toBe(401)
    })

    it('POST /run accepts shared_secret requests with the right bearer token', async () => {
        const resolver = makeResolver(makeRevision({ auth: { mode: 'shared_secret', token: 'sekret' } }))
        harness = await startServer({ resolver })
        const res = await supertest(harness.app)
            .post('/run')
            .set('x-original-host', 'analytics-bot.agents.posthog.com')
            .set('authorization', 'Bearer sekret')
            .send({})
        expect(res.status).toBe(202)
    })

    it('POST /send/:id publishes to the bus input channel', async () => {
        harness = await startServer()
        const received: SessionInputMessage[] = []
        await harness.bus.subscribeInput('abc', (m) => received.push(m))

        const res = await supertest(harness.app).post('/send/abc').send({ content: 'hi' })
        expect(res.status).toBe(202)
        expect(received).toEqual([expect.objectContaining({ type: 'user_message', content: 'hi' })])
    })

    it('POST /send/:id rejects empty content', async () => {
        harness = await startServer()
        const res = await supertest(harness.app).post('/send/abc').send({ content: '' })
        expect(res.status).toBe(400)
    })

    it('POST /run with explicit applicationId bypasses host', async () => {
        harness = await startServer()
        const res = await supertest(harness.app)
            .post('/run')
            .send({ applicationId: 'b1f3d6e4-4c2a-4b0e-9d5a-1c9f7e1d8a01' })
        expect(res.status).toBe(202)
        expect(harness.queue.created).toHaveLength(1)
    })
})
