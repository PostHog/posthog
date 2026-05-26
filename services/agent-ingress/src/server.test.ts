import supertest from 'supertest'
import type { Express } from 'ultimate-express'

import {
    ApplicationsRepository,
    IdentitiesRepository,
    InMemorySessionBus,
    ResolvedRevision,
    SessionInputMessage,
} from '@posthog/agent-core'

import { RevisionResolver } from './resolver'
import { ServerDeps, buildServer } from './server'

class FakeQueue {
    public created: Array<Record<string, unknown>> = []
    private idCounter = 0
    /** Returns the principal `createJob` was called with for that id, or `null` for unknown ids. */
    async createJob(input: Record<string, unknown>): Promise<string> {
        this.created.push(input)
        this.idCounter += 1
        return `session-${this.idCounter}`
    }
    async getPrincipal(_sessionId: string): Promise<null> {
        // Public-by-default test agents stamp no principal — return null so
        // strict-match treats existing sessions as principal-less and ungated.
        return null
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

function makeRepository(env: Record<string, string> = {}): ApplicationsRepository {
    return {
        decryptEnv: async () => env,
        resolveByDomain: async () => null,
        resolveBySlug: async () => null,
        resolveById: async () => null,
        verifyTokenIdentity: async (teamId: number) => ({
            kind: 'service' as const,
            orgId: String(teamId),
            caller: 'team-secret',
        }),
    } as unknown as ApplicationsRepository
}

function makeIdentities(): IdentitiesRepository {
    // Test fixture — agents without `identity:` blocks never invoke this.
    // The few tests that exercise an identity-declaring agent override the
    // `resolveIdentity` callback on `ServerDeps` directly.
    return {
        resolveIdentity: async () => {
            throw new Error('IdentitiesRepository not stubbed in this test')
        },
    } as unknown as IdentitiesRepository
}

interface TestHarness {
    queue: FakeQueue
    bus: InMemorySessionBus
    app: Express
    teardown: () => Promise<void>
}

async function startServer(overrides: Partial<ServerDeps> = {}): Promise<TestHarness> {
    const queue = new FakeQueue()
    const bus = new InMemorySessionBus()
    const resolver = makeResolver(makeRevision())
    const repository = makeRepository()
    const deps: ServerDeps = {
        queue: queue as unknown as ServerDeps['queue'],
        bus,
        resolver,
        repository,
        identities: makeIdentities(),
        domainSuffix: '.agents.posthog.com',
        routingMode: 'domain',
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

    it('GET /health returns ok (bypasses tenant resolution)', async () => {
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

    it('POST /run enqueues a job via the wildcard handler + ass-server route', async () => {
        harness = await startServer()
        const res = await supertest(harness.app)
            .post('/run')
            .set('x-original-host', 'analytics-bot.agents.posthog.com')
            .set('content-type', 'application/json')
            .send({ foo: 'bar' })
        expect(res.status).toBe(202)
        expect(res.body.sessionId).toBe('session-1')
        expect(res.body.trigger).toEqual({ id: 'http', type: 'http_invoke' })
        expect(harness.queue.created).toHaveLength(1)
        expect(harness.queue.created[0]).toMatchObject({
            teamId: 7,
            applicationId: 'b1f3d6e4-4c2a-4b0e-9d5a-1c9f7e1d8a01',
            revisionId: 'b1f3d6e4-4c2a-4b0e-9d5a-1c9f7e1d8a02',
            queueName: 'default',
        })
    })

    it('returns 409 when the resolved revision is not ready', async () => {
        const resolver = makeResolver(makeRevision({ revisionState: 'uploaded' }))
        harness = await startServer({ resolver })
        const res = await supertest(harness.app)
            .post('/run')
            .set('x-original-host', 'analytics-bot.agents.posthog.com')
            .send({})
        expect(res.status).toBe(409)
    })

    it('returns 404 when no application matches the host', async () => {
        const resolver = makeResolver(null)
        harness = await startServer({ resolver })
        const res = await supertest(harness.app)
            .post('/run')
            .set('x-original-host', 'unknown.agents.posthog.com')
            .send({})
        expect(res.status).toBe(404)
    })

    it('returns 400 when the host does not match the configured suffix', async () => {
        harness = await startServer()
        const res = await supertest(harness.app).post('/run').set('x-original-host', 'evil.example.com').send({})
        expect(res.status).toBe(400)
    })

    it('authenticatePat callback signature is (teamId, token) and stays unbound from request team', async () => {
        // The fixture revision is `auth: public`, so the callback isn't invoked
        // for this path. The assertion is that the signature is the team-scoped
        // shape; negative-auth behavior is covered in @repo/ass-server's tests.
        const calls: Array<{ teamId: number; token: string }> = []
        harness = await startServer({
            authenticatePat: async (teamId, token) => {
                calls.push({ teamId, token })
                return { kind: 'service', orgId: String(teamId), caller: 'team-secret' }
            },
        })
        const res = await supertest(harness.app)
            .post('/run')
            .set('x-original-host', 'analytics-bot.agents.posthog.com')
            .send({})
        expect(res.status).toBe(202)
        expect(calls).toHaveLength(0)
    })

    it('POST /send/:id routes through route() → control:send → bus.publishInput', async () => {
        harness = await startServer()
        const received: SessionInputMessage[] = []
        await harness.bus.subscribeInput('abc', (m) => received.push(m))

        const res = await supertest(harness.app)
            .post('/send/abc')
            .set('x-original-host', 'analytics-bot.agents.posthog.com')
            .send({ content: 'hi' })
        expect(res.status).toBe(202)
        expect(received).toEqual([expect.objectContaining({ type: 'user_message', content: 'hi' })])
    })

    it('POST /send/:id with empty content → 400', async () => {
        harness = await startServer()
        const res = await supertest(harness.app)
            .post('/send/abc')
            .set('x-original-host', 'analytics-bot.agents.posthog.com')
            .send({ content: '' })
        expect(res.status).toBe(400)
    })

    it('unknown paths return 404 via the wildcard handler', async () => {
        harness = await startServer()
        const res = await supertest(harness.app)
            .post('/totally-unknown')
            .set('x-original-host', 'analytics-bot.agents.posthog.com')
            .send({})
        expect(res.status).toBe(404)
    })
})
