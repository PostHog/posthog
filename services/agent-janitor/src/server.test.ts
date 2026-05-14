import { DateTime } from 'luxon'
import supertest from 'supertest'
import type { Express } from 'ultimate-express'

import { ListSessionsFilter, SessionQuery, SessionView } from '@posthog/agent-core'

import { JanitorServerDeps, buildServer } from './server'

const VALID_UUID = 'b1f3d6e4-4c2a-4b0e-9d5a-1c9f7e1d8a01'
const OTHER_UUID = 'b1f3d6e4-4c2a-4b0e-9d5a-1c9f7e1d8a02'
const SHARED_KEY = 'unit-test-internal-key'

class FakeSessionQuery {
    public lastList: ListSessionsFilter | null = null
    public canceled: string[] = []

    constructor(private readonly rows: SessionView[]) {}

    findSession = async (id: string): Promise<SessionView | null> => this.rows.find((r) => r.id === id) ?? null

    listSessions = async (filter: ListSessionsFilter): Promise<SessionView[]> => {
        this.lastList = filter
        return this.rows.filter((row) => {
            if (filter.teamId !== undefined && row.teamId !== filter.teamId) {
                return false
            }
            if (filter.applicationId && row.applicationId !== filter.applicationId) {
                return false
            }
            if (filter.revisionId && row.revisionId !== filter.revisionId) {
                return false
            }
            if (filter.status) {
                const statuses = Array.isArray(filter.status) ? filter.status : [filter.status]
                if (!statuses.includes(row.status)) {
                    return false
                }
            }
            return true
        })
    }

    cancelSession = async (id: string): Promise<SessionView | null> => {
        const row = this.rows.find((r) => r.id === id)
        if (!row) {
            return null
        }
        this.canceled.push(id)
        return { ...row, status: 'canceled' }
    }
}

function makeView(overrides: Partial<SessionView> = {}): SessionView {
    const now = DateTime.utc()
    return {
        id: VALID_UUID,
        teamId: 7,
        applicationId: 'b1f3d6e4-4c2a-4b0e-9d5a-1c9f7e1d8a03',
        revisionId: 'b1f3d6e4-4c2a-4b0e-9d5a-1c9f7e1d8a04',
        queueName: 'default',
        status: 'running',
        scheduled: now,
        created: now,
        lastTransition: now,
        lastHeartbeat: now,
        transitionCount: 1,
        janitorTouchCount: 0,
        stateByteSize: 42,
        ...overrides,
    }
}

interface TestHarness {
    query: FakeSessionQuery
    app: Express
}

async function startServer(args: {
    rows?: SessionView[]
    sharedKey?: string | undefined
}): Promise<TestHarness> {
    const query = new FakeSessionQuery(args.rows ?? [])
    const deps: JanitorServerDeps = {
        query: query as unknown as SessionQuery,
        internalApiSharedKey: args.sharedKey,
    }
    const app = buildServer(deps)
    await new Promise<void>((resolve, reject) => {
        try {
            app.listen(0, () => resolve())
        } catch (err) {
            reject(err)
        }
    })
    return { query, app }
}

describe('agent-janitor server', () => {
    let harness: TestHarness

    afterEach(() => {
        // app does not expose close() in ultimate-express, and the supertest agent does
        // not hold onto the underlying server; relying on jest --forceExit to tear it down.
    })

    describe('public routes', () => {
        it('GET /health is open and returns ok', async () => {
            harness = await startServer({ sharedKey: SHARED_KEY })
            const res = await supertest(harness.app).get('/health')
            expect(res.status).toBe(200)
            expect(res.body).toEqual({ ok: true })
        })

        it('GET /metrics is open and returns prometheus text', async () => {
            harness = await startServer({ sharedKey: SHARED_KEY })
            const res = await supertest(harness.app).get('/metrics')
            expect(res.status).toBe(200)
            expect(res.headers['content-type']).toContain('text/plain')
        })
    })

    describe('auth gating on /internal/*', () => {
        it('refuses with 500 when no shared key is configured', async () => {
            harness = await startServer({ rows: [makeView()], sharedKey: undefined })
            const res = await supertest(harness.app).get(`/internal/sessions/${VALID_UUID}`)
            expect(res.status).toBe(500)
        })

        it('refuses with 401 when the key is missing', async () => {
            harness = await startServer({ rows: [makeView()], sharedKey: SHARED_KEY })
            const res = await supertest(harness.app).get(`/internal/sessions/${VALID_UUID}`)
            expect(res.status).toBe(401)
        })

        it('refuses with 401 when the key is wrong', async () => {
            harness = await startServer({ rows: [makeView()], sharedKey: SHARED_KEY })
            const res = await supertest(harness.app)
                .get(`/internal/sessions/${VALID_UUID}`)
                .set('x-internal-key', 'not-the-key')
            expect(res.status).toBe(401)
        })

        it('accepts with 200 when the key matches', async () => {
            harness = await startServer({ rows: [makeView()], sharedKey: SHARED_KEY })
            const res = await supertest(harness.app)
                .get(`/internal/sessions/${VALID_UUID}`)
                .set('x-internal-key', SHARED_KEY)
            expect(res.status).toBe(200)
        })
    })

    describe('GET /internal/sessions/:id', () => {
        it('returns the session as snake_case JSON', async () => {
            harness = await startServer({ rows: [makeView()], sharedKey: SHARED_KEY })
            const res = await supertest(harness.app)
                .get(`/internal/sessions/${VALID_UUID}`)
                .set('x-internal-key', SHARED_KEY)
            expect(res.status).toBe(200)
            expect(res.body).toMatchObject({
                id: VALID_UUID,
                team_id: 7,
                status: 'running',
                queue_name: 'default',
                state_byte_size: 42,
            })
        })

        it('returns 404 when the session does not exist', async () => {
            harness = await startServer({ rows: [], sharedKey: SHARED_KEY })
            const res = await supertest(harness.app)
                .get(`/internal/sessions/${VALID_UUID}`)
                .set('x-internal-key', SHARED_KEY)
            expect(res.status).toBe(404)
        })

        it('returns 400 for non-uuid ids', async () => {
            harness = await startServer({ rows: [], sharedKey: SHARED_KEY })
            const res = await supertest(harness.app)
                .get('/internal/sessions/not-a-uuid')
                .set('x-internal-key', SHARED_KEY)
            expect(res.status).toBe(400)
        })
    })

    describe('GET /internal/sessions', () => {
        it('lists sessions filtered by application_id + status', async () => {
            const rowA = makeView({ id: VALID_UUID, status: 'running' })
            const rowB = makeView({ id: OTHER_UUID, status: 'completed' })
            harness = await startServer({ rows: [rowA, rowB], sharedKey: SHARED_KEY })

            const res = await supertest(harness.app)
                .get(`/internal/sessions?application_id=${rowA.applicationId}&status=running`)
                .set('x-internal-key', SHARED_KEY)

            expect(res.status).toBe(200)
            expect(res.body.results).toHaveLength(1)
            expect(res.body.results[0].id).toBe(VALID_UUID)
            expect(harness.query.lastList).toMatchObject({
                applicationId: rowA.applicationId,
                status: ['running'],
            })
        })

        it('rejects invalid query parameters', async () => {
            harness = await startServer({ rows: [], sharedKey: SHARED_KEY })
            const res = await supertest(harness.app)
                .get('/internal/sessions?application_id=not-a-uuid')
                .set('x-internal-key', SHARED_KEY)
            expect(res.status).toBe(400)
        })
    })

    describe('POST /internal/sessions/:id/cancel', () => {
        it('cancels an existing session and returns the new view', async () => {
            harness = await startServer({ rows: [makeView()], sharedKey: SHARED_KEY })
            const res = await supertest(harness.app)
                .post(`/internal/sessions/${VALID_UUID}/cancel`)
                .set('x-internal-key', SHARED_KEY)
            expect(res.status).toBe(200)
            expect(res.body.status).toBe('canceled')
            expect(harness.query.canceled).toEqual([VALID_UUID])
        })

        it('returns 404 when the session does not exist', async () => {
            harness = await startServer({ rows: [], sharedKey: SHARED_KEY })
            const res = await supertest(harness.app)
                .post(`/internal/sessions/${VALID_UUID}/cancel`)
                .set('x-internal-key', SHARED_KEY)
            expect(res.status).toBe(404)
        })

        it('returns 400 for non-uuid ids', async () => {
            harness = await startServer({ rows: [], sharedKey: SHARED_KEY })
            const res = await supertest(harness.app)
                .post('/internal/sessions/not-a-uuid/cancel')
                .set('x-internal-key', SHARED_KEY)
            expect(res.status).toBe(400)
        })
    })
})
