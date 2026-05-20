import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'
import { Pool } from 'pg'
import { v7 as uuidv7 } from 'uuid'

/**
 * DB-gated queue integration tests.
 *
 * Skipped automatically if AGENT_RUNTIME_QUEUE_TEST_DATABASE_URL is unset, so this
 * suite is safe in environments without a Postgres available.
 */
import { DequeuedSessionJob, SessionQuery, SessionQueueJanitor, SessionQueueManager, SessionQueueWorker } from '..'

const DB_URL = process.env.AGENT_RUNTIME_QUEUE_TEST_DATABASE_URL
const describeIfDb = DB_URL ? describe : describe.skip

describeIfDb('agent-core queue (DB-gated)', () => {
    let pool: Pool
    let manager: SessionQueueManager
    let worker: SessionQueueWorker

    beforeAll(async () => {
        pool = new Pool({ connectionString: DB_URL })
        await pool.query(`DROP TABLE IF EXISTS agent_sessions`)
        await pool.query(`DROP TABLE IF EXISTS _sqlx_migrations`)
        await pool.query(`DROP TYPE IF EXISTS AgentSessionStatus`)

        // Canonical migrations live in rust/agent_runtime_queue_migrations/, applied via
        // sqlx in production. For this DB-gated suite we replay them in lexicographic
        // order directly so we don't need sqlx-cli on the test machine.
        const migrationsDir = join(__dirname, '..', '..', '..', '..', 'rust', 'agent_runtime_queue_migrations')
        const files = readdirSync(migrationsDir)
            .filter((f) => f.endsWith('.sql'))
            .sort()
        for (const file of files) {
            await pool.query(readFileSync(join(migrationsDir, file), 'utf8'))
        }
    })

    afterAll(async () => {
        await pool.end()
    })

    beforeEach(async () => {
        await pool.query('TRUNCATE agent_sessions')
        manager = new SessionQueueManager({
            pool: { dbUrl: DB_URL! },
            depthLimit: 1_000,
            depthCheckIntervalMs: 0,
        })
        // Default test worker — small concurrency, fast poll, no heartbeat noise.
        await manager.connect()
        worker = new SessionQueueWorker({
            pool: { dbUrl: DB_URL! },
            queueName: 'test-queue',
            concurrency: 10,
            pollDelayMs: 5,
            heartbeatIntervalMs: 0,
        })
    })

    afterEach(async () => {
        await worker.disconnect()
        await manager.disconnect()
    })

    /**
     * Grab the first job the worker dequeues. The handler resolves the outer
     * promise with the job and stays parked until externally released — that's
     * fine because each test ack/fail/reschedules the job itself, and the
     * surrounding `afterEach` tears the worker down anyway.
     */
    async function consumeOne(): Promise<DequeuedSessionJob> {
        return new Promise<DequeuedSessionJob>((resolve) => {
            void worker.connect(async (job) => {
                resolve(job)
                await worker.stopConsuming()
            })
        })
    }

    it('enqueue → dequeue → ack moves status through running → completed', async () => {
        const id = await manager.createJob({ teamId: 42, queueName: 'test-queue' })
        const job = await consumeOne()
        expect(job.id).toBe(id)
        expect(job.teamId).toBe(42)
        await job.ack()

        const { rows } = await pool.query<{ status: string }>('SELECT status FROM agent_sessions WHERE id = $1', [id])
        expect(rows[0].status).toBe('completed')
    })

    it('reschedule round-trips state', async () => {
        await manager.createJob({
            teamId: 1,
            queueName: 'test-queue',
            state: Buffer.from('hello'),
        })
        const first = await consumeOne()
        await first.reschedule({ scheduledAt: new Date(), state: Buffer.from('world') })

        worker = new SessionQueueWorker({
            pool: { dbUrl: DB_URL! },
            queueName: 'test-queue',
            concurrency: 10,
            pollDelayMs: 5,
            heartbeatIntervalMs: 0,
        })
        const second = await consumeOne()
        expect(second.state?.toString('utf8')).toBe('world')
    })

    it('SessionQuery.findSession / listSessions / cancelSession', async () => {
        const appA = '11111111-1111-4111-8111-111111111111'
        const appB = '22222222-2222-4222-8222-222222222222'
        await manager.createJob({ teamId: 1, applicationId: appA, queueName: 'test-queue' })
        await manager.createJob({ teamId: 1, applicationId: appA, queueName: 'test-queue' })
        await manager.createJob({ teamId: 2, applicationId: appB, queueName: 'test-queue' })

        const query = new SessionQuery({ pool: { dbUrl: DB_URL! } })
        try {
            await query.connect()

            // findSession returns null for unknown ids.
            const unknown = await query.findSession('99999999-9999-4999-8999-999999999999')
            expect(unknown).toBeNull()

            // listSessions filters by application.
            const onlyAppA = await query.listSessions({ applicationId: appA })
            expect(onlyAppA).toHaveLength(2)

            // listSessions filters by status; everything is 'available' right now.
            const completed = await query.listSessions({ status: 'completed' })
            expect(completed).toHaveLength(0)

            // cancelSession moves an available row to canceled and returns the new view.
            const toCancel = onlyAppA[0]
            const canceled = await query.cancelSession(toCancel.id)
            expect(canceled?.status).toBe('canceled')
            const refound = await query.findSession(toCancel.id)
            expect(refound?.status).toBe('canceled')

            // Cancelling a canceled row is a no-op; we still return the current view.
            const noop = await query.cancelSession(toCancel.id)
            expect(noop?.status).toBe('canceled')
        } finally {
            await query.disconnect()
        }
    })

    it('janitor resets stalled jobs and fails poison pills', async () => {
        const id = await manager.createJob({ teamId: 1, queueName: 'test-queue' })
        // Force the job into 'running' with an ancient heartbeat to simulate a stall.
        await pool.query(
            `UPDATE agent_sessions
             SET status = 'running', lock_id = $2, last_heartbeat = NOW() - INTERVAL '1 hour'
             WHERE id = $1`,
            [id, uuidv7()]
        )

        const janitor = new SessionQueueJanitor({
            pool: { dbUrl: DB_URL! },
            cleanupGraceMs: 0,
            stallTimeoutMs: 1,
            maxTouchCount: 1,
        })
        try {
            const first = await janitor.runOnce()
            expect(first.stalled).toBe(1)

            // Stall again to push touch count past the threshold.
            await pool.query(
                `UPDATE agent_sessions
                 SET status = 'running', lock_id = $2, last_heartbeat = NOW() - INTERVAL '1 hour'
                 WHERE id = $1`,
                [id, uuidv7()]
            )
            const second = await janitor.runOnce()
            expect(second.poisoned).toBe(1)

            const { rows } = await pool.query<{ status: string }>('SELECT status FROM agent_sessions WHERE id = $1', [
                id,
            ])
            expect(rows[0].status).toBe('failed')
        } finally {
            await janitor.stop()
        }
    })

    it('respects the concurrency cap: max N in flight, releases unblock new dequeues', async () => {
        // Five jobs, concurrency cap of 2. We hold the handler open until each
        // job is manually released, then assert that no more than `concurrency`
        // ever run at the same time and that releases trigger new pickups.
        const ids: string[] = []
        for (let i = 0; i < 5; i++) {
            ids.push(await manager.createJob({ teamId: 1, queueName: 'test-queue' }))
        }

        await worker.disconnect()
        worker = new SessionQueueWorker({
            pool: { dbUrl: DB_URL! },
            queueName: 'test-queue',
            concurrency: 2,
            pollDelayMs: 5,
            heartbeatIntervalMs: 0,
        })

        const released = new Map<string, () => void>()
        const inFlight = new Set<string>()
        let peak = 0
        const dequeuedOrder: string[] = []
        const completed: string[] = []

        await worker.connect(async (job) => {
            inFlight.add(job.id)
            dequeuedOrder.push(job.id)
            peak = Math.max(peak, inFlight.size)
            await new Promise<void>((resolve) => released.set(job.id, resolve))
            inFlight.delete(job.id)
            await job.ack()
            completed.push(job.id)
        })

        // Let the worker pick up the first batch (capped at 2).
        await waitUntil(() => dequeuedOrder.length >= 2)
        expect(dequeuedOrder).toHaveLength(2)
        expect(inFlight.size).toBe(2)

        // Release them one by one and confirm a new one picks up each time.
        released.get(dequeuedOrder[0])!()
        await waitUntil(() => dequeuedOrder.length >= 3)
        expect(inFlight.size).toBe(2)

        released.get(dequeuedOrder[1])!()
        await waitUntil(() => dequeuedOrder.length >= 4)
        expect(inFlight.size).toBe(2)

        released.get(dequeuedOrder[2])!()
        await waitUntil(() => dequeuedOrder.length >= 5)
        expect(inFlight.size).toBe(2)

        // Drain the last two.
        released.get(dequeuedOrder[3])!()
        released.get(dequeuedOrder[4])!()
        await waitUntil(() => completed.length === 5)

        expect(peak).toBe(2)
        expect(new Set(completed)).toEqual(new Set(ids))
    })

    it('handler error leaves the row in running for the janitor to reap', async () => {
        const id = await manager.createJob({ teamId: 1, queueName: 'test-queue' })

        const seen: string[] = []
        await worker.connect(async (job) => {
            seen.push(job.id)
            await worker.stopConsuming()
            throw new Error('boom')
        })
        // Give the handler a tick to propagate the rejection through runOne.
        await waitUntil(() => seen.includes(id))
        await waitUntil(async () => {
            const { rows } = await pool.query<{ status: string; lock_id: string | null }>(
                'SELECT status, lock_id FROM agent_sessions WHERE id = $1',
                [id]
            )
            return rows[0]?.status === 'running' && rows[0]?.lock_id !== null
        })

        const { rows } = await pool.query<{ status: string; lock_id: string | null }>(
            'SELECT status, lock_id FROM agent_sessions WHERE id = $1',
            [id]
        )
        expect(rows[0].status).toBe('running')
        expect(rows[0].lock_id).not.toBeNull()
    })
})

/** Poll a predicate until it returns truthy or the timeout elapses. */
async function waitUntil(predicate: () => boolean | Promise<boolean>, timeoutMs = 2_000): Promise<void> {
    const start = Date.now()
    while (Date.now() - start < timeoutMs) {
        if (await predicate()) {
            return
        }
        await new Promise((r) => setTimeout(r, 10))
    }
    throw new Error(`waitUntil: predicate never satisfied within ${timeoutMs}ms`)
}
