import { DateTime } from 'luxon'
import { Pool } from 'pg'
import { v7 as uuidv7 } from 'uuid'

import { logger } from '../logger'
import { DequeuedSessionJob, RescheduleOptions, RescheduleOptionsSchema, WorkerConfig } from './types'

interface RawSessionRow {
    id: string
    team_id: number
    application_id: string | null
    revision_id: string | null
    queue_name: string
    scheduled: string
    created: string
    transition_count: number
    state: Buffer | null
    lock_id: string
}

function sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms))
}

export class SessionQueueWorker {
    private pool: Pool
    private isConsuming = false
    private lastPollTime = new Date()
    private consumerLoopPromise: Promise<void> | null = null

    private readonly batchMaxSize: number
    private readonly pollDelayMs: number
    private readonly heartbeatTimeoutMs: number
    private readonly includeEmptyBatches: boolean

    constructor(private config: WorkerConfig) {
        this.pool = new Pool({
            connectionString: config.pool.dbUrl,
            max: config.pool.maxConnections ?? 10,
            idleTimeoutMillis: config.pool.idleTimeoutMs ?? 30_000,
        })
        this.batchMaxSize = config.batchMaxSize ?? 100
        this.pollDelayMs = config.pollDelayMs ?? 50
        this.heartbeatTimeoutMs = config.heartbeatTimeoutMs ?? 30_000
        this.includeEmptyBatches = config.includeEmptyBatches ?? false
    }

    async connect(processBatch: (jobs: DequeuedSessionJob[]) => Promise<void>): Promise<void> {
        const client = await this.pool.connect()
        client.release()
        this.isConsuming = true
        this.consumerLoopPromise = this.runConsumerLoop(processBatch)
    }

    private async runConsumerLoop(processBatch: (jobs: DequeuedSessionJob[]) => Promise<void>): Promise<void> {
        while (this.isConsuming) {
            try {
                this.lastPollTime = new Date()
                const rows = await this.dequeueJobs()
                if (rows.length === 0) {
                    if (this.includeEmptyBatches) {
                        await processBatch([])
                    }
                    await sleep(this.pollDelayMs)
                    continue
                }
                const jobs = rows.map((row) => this.wrapJob(row))
                await processBatch(jobs)
            } catch (err) {
                logger.error('SessionQueueWorker consumer loop error', { error: String(err) })
                await sleep(this.pollDelayMs)
            }
        }
    }

    private async dequeueJobs(): Promise<RawSessionRow[]> {
        const lockId = uuidv7()
        const result = await this.pool.query<RawSessionRow>(
            `WITH available AS (
                SELECT id
                FROM agent_sessions
                WHERE status = 'available'
                  AND queue_name = $1
                  AND scheduled <= NOW()
                ORDER BY scheduled ASC
                LIMIT $2
                FOR UPDATE SKIP LOCKED
            )
            UPDATE agent_sessions
            SET status = 'running',
                lock_id = $3,
                last_heartbeat = NOW(),
                last_transition = NOW(),
                transition_count = transition_count + 1
            FROM available
            WHERE agent_sessions.id = available.id
            RETURNING
                agent_sessions.id,
                agent_sessions.team_id,
                agent_sessions.application_id,
                agent_sessions.revision_id,
                agent_sessions.queue_name,
                agent_sessions.scheduled,
                agent_sessions.created,
                agent_sessions.transition_count,
                agent_sessions.state,
                agent_sessions.lock_id`,
            [this.config.queueName, this.batchMaxSize, lockId]
        )
        return result.rows.sort((a, b) => new Date(a.scheduled).getTime() - new Date(b.scheduled).getTime())
    }

    private wrapJob(row: RawSessionRow): DequeuedSessionJob {
        const pool = this.pool
        const lockId = row.lock_id
        let released = false

        const releaseGuard = (method: string): void => {
            if (released) {
                throw new Error(`Session ${row.id} already released, cannot call ${method}`)
            }
            released = true
        }

        return {
            id: row.id,
            teamId: row.team_id,
            applicationId: row.application_id,
            revisionId: row.revision_id,
            queueName: row.queue_name,
            scheduled: DateTime.fromISO(row.scheduled, { zone: 'utc' }),
            created: DateTime.fromISO(row.created, { zone: 'utc' }),
            transitionCount: row.transition_count,
            state: row.state,

            async ack(): Promise<void> {
                releaseGuard('ack')
                await pool.query(
                    `UPDATE agent_sessions
                     SET status = 'completed', lock_id = NULL, last_heartbeat = NULL,
                         last_transition = NOW(), transition_count = transition_count + 1
                     WHERE id = $1 AND lock_id = $2`,
                    [row.id, lockId]
                )
            },

            async fail(): Promise<void> {
                releaseGuard('fail')
                await pool.query(
                    `UPDATE agent_sessions
                     SET status = 'failed', lock_id = NULL, last_heartbeat = NULL,
                         last_transition = NOW(), transition_count = transition_count + 1
                     WHERE id = $1 AND lock_id = $2`,
                    [row.id, lockId]
                )
            },

            async reschedule(input?: RescheduleOptions): Promise<void> {
                releaseGuard('reschedule')
                const options = input ? RescheduleOptionsSchema.parse(input) : undefined
                const scheduled = options?.scheduledAt ?? new Date()
                const setClauses = [
                    `status = 'available'`,
                    `lock_id = NULL`,
                    `last_heartbeat = NULL`,
                    `last_transition = NOW()`,
                    `transition_count = transition_count + 1`,
                    `scheduled = $3`,
                ]
                const params: unknown[] = [row.id, lockId, scheduled]
                if (options?.state !== undefined) {
                    params.push(options.state ?? null)
                    setClauses.push(`state = $${params.length}`)
                    params.push(options.state ? options.state.byteLength : null)
                    setClauses.push(`state_byte_size = $${params.length}`)
                }
                await pool.query(
                    `UPDATE agent_sessions SET ${setClauses.join(', ')}
                     WHERE id = $1 AND lock_id = $2`,
                    params
                )
            },

            async cancel(): Promise<void> {
                releaseGuard('cancel')
                await pool.query(
                    `UPDATE agent_sessions
                     SET status = 'canceled', lock_id = NULL, last_heartbeat = NULL,
                         last_transition = NOW(), transition_count = transition_count + 1
                     WHERE id = $1 AND lock_id = $2`,
                    [row.id, lockId]
                )
            },

            async heartbeat(): Promise<void> {
                if (released) {
                    throw new Error(`Session ${row.id} already released, cannot heartbeat`)
                }
                await pool.query(
                    `UPDATE agent_sessions
                     SET last_heartbeat = NOW()
                     WHERE id = $1 AND lock_id = $2`,
                    [row.id, lockId]
                )
            },
        }
    }

    isHealthy(): boolean {
        return this.isConsuming && Date.now() - this.lastPollTime.getTime() < this.heartbeatTimeoutMs
    }

    async stopConsuming(): Promise<void> {
        this.isConsuming = false
        if (this.consumerLoopPromise) {
            await this.consumerLoopPromise
            this.consumerLoopPromise = null
        }
    }

    async disconnect(): Promise<void> {
        await this.stopConsuming()
        await this.pool.end()
    }
}
