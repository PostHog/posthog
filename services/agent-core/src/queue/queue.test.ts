import { readFileSync } from 'node:fs'
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
        const schema = readFileSync(join(__dirname, '..', '..', 'migrations', '0001_initial_schema.sql'), 'utf8')
        await pool.query(`DROP TABLE IF EXISTS agent_sessions`)
        await pool.query(`DROP TABLE IF EXISTS agent_runtime_migrations`)
        await pool.query(`DROP TYPE IF EXISTS AgentSessionStatus`)
        await pool.query(schema)
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
        await manager.connect()
        worker = new SessionQueueWorker({
            pool: { dbUrl: DB_URL! },
            queueName: 'test-queue',
            batchMaxSize: 10,
            pollDelayMs: 5,
            includeEmptyBatches: false,
        })
    })

    afterEach(async () => {
        await worker.disconnect()
        await manager.disconnect()
    })

    async function consumeOnce(): Promise<DequeuedSessionJob[]> {
        return new Promise<DequeuedSessionJob[]>((resolve) => {
            worker.connect(async (batch) => {
                if (batch.length > 0) {
                    resolve(batch)
                    await worker.stopConsuming()
                }
            })
        })
    }

    it('enqueue → dequeue → ack moves status through running → completed', async () => {
        const id = await manager.createJob({ teamId: 42, queueName: 'test-queue' })
        const batch = await consumeOnce()
        expect(batch).toHaveLength(1)
        expect(batch[0].id).toBe(id)
        expect(batch[0].teamId).toBe(42)
        await batch[0].ack()

        const { rows } = await pool.query<{ status: string }>('SELECT status FROM agent_sessions WHERE id = $1', [id])
        expect(rows[0].status).toBe('completed')
    })

    it('reschedule round-trips state', async () => {
        await manager.createJob({
            teamId: 1,
            queueName: 'test-queue',
            state: Buffer.from('hello'),
        })
        const first = await consumeOnce()
        await first[0].reschedule({ scheduledAt: new Date(), state: Buffer.from('world') })

        worker = new SessionQueueWorker({
            pool: { dbUrl: DB_URL! },
            queueName: 'test-queue',
            batchMaxSize: 10,
            pollDelayMs: 5,
        })
        const second = await consumeOnce()
        expect(second[0].state?.toString('utf8')).toBe('world')
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
})
