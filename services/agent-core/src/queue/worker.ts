import type { Principal } from '@repo/ass-server/types'
import { DateTime } from 'luxon'
import { Pool } from 'pg'
import { v7 as uuidv7 } from 'uuid'

import { logger } from '../logger'
import { createAgentPgPool } from '../postgres'
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
    /** JSONB column; pg deserializes to a structured object. NULL when the agent is public. */
    principal: Principal | null
}

export type SessionJobHandler = (job: DequeuedSessionJob) => Promise<void>

/**
 * Polls `agent_sessions` and hands rows to a per-job `handler`, bounded by a
 * concurrency cap. The fetcher is single-flight — only one SELECT FOR UPDATE
 * runs at a time, and it only requests `concurrency - inFlight` rows so we
 * never overfetch. When a handler settles (ack/fail/reschedule/handler return),
 * the slot is released and the fetcher is signaled to look for more work.
 *
 * Heartbeats are owned here, not by the handler: every in-flight job has a
 * `setInterval` pinging `last_heartbeat` that auto-clears on settle. The
 * handler is responsible for calling one of ack/fail/reschedule/cancel on
 * the job; if it throws or returns without releasing, the row stays in
 * `running` until the janitor's stall reaper picks it up.
 */
export class SessionQueueWorker {
    private pool: Pool
    private isConsuming = false
    private lastTickTime = new Date()
    private fetcherLoopPromise: Promise<void> | null = null

    private readonly concurrency: number
    private readonly pollDelayMs: number
    private readonly heartbeatTimeoutMs: number
    private readonly heartbeatIntervalMs: number
    private readonly drainTimeoutMs: number

    private inFlight = 0
    /** Waiters parked on a slot becoming free. FIFO. */
    private slotWakers: Array<() => void> = []
    /** In-flight handler promises — drained on `disconnect()`. */
    private activeJobs = new Set<Promise<void>>()

    constructor(private config: WorkerConfig) {
        this.pool = createAgentPgPool(config.pool, 10)
        this.concurrency = Math.max(1, config.concurrency ?? 8)
        this.pollDelayMs = config.pollDelayMs ?? 50
        this.heartbeatTimeoutMs = config.heartbeatTimeoutMs ?? 30_000
        this.heartbeatIntervalMs = config.heartbeatIntervalMs ?? 5_000
        this.drainTimeoutMs = config.drainTimeoutMs ?? 30_000
    }

    async connect(handler: SessionJobHandler): Promise<void> {
        const client = await this.pool.connect()
        client.release()
        this.isConsuming = true
        this.fetcherLoopPromise = this.runFetcherLoop(handler)
    }

    private async runFetcherLoop(handler: SessionJobHandler): Promise<void> {
        while (this.isConsuming) {
            this.lastTickTime = new Date()

            // Block until at least one slot is open. signalSlotFreed wakes us.
            while (this.isConsuming && this.inFlight >= this.concurrency) {
                await this.waitForSlot()
                this.lastTickTime = new Date()
            }
            if (!this.isConsuming) {
                break
            }

            const wanted = this.concurrency - this.inFlight
            let rows: RawSessionRow[]
            try {
                rows = await this.dequeueJobs(wanted)
            } catch (err) {
                logger.error('SessionQueueWorker dequeue failed', { error: String(err) })
                await sleep(this.pollDelayMs)
                continue
            }

            if (rows.length === 0) {
                // Queue empty AND slots available — a slot freeing doesn't help
                // us here (the queue is still empty), so a plain sleep is right.
                await sleep(this.pollDelayMs)
                continue
            }

            for (const row of rows) {
                this.inFlight++
                const job = this.wrapJob(row)
                const p = this.runOne(job, handler)
                this.activeJobs.add(p)
                void p.finally(() => this.activeJobs.delete(p))
            }
        }
    }

    private async runOne(job: DequeuedSessionJob, handler: SessionJobHandler): Promise<void> {
        const hb =
            this.heartbeatIntervalMs > 0
                ? setInterval(() => {
                      void job.heartbeat().catch((err) => {
                          // `heartbeat()` throws if the job has already been released —
                          // expected when the handler ack/fail/reschedule'd mid-interval.
                          const msg = err instanceof Error ? err.message : String(err)
                          if (msg.includes('already released')) {
                              return
                          }
                          logger.warn('SessionQueueWorker heartbeat failed', {
                              sessionId: job.id,
                              error: msg,
                          })
                      })
                  }, this.heartbeatIntervalMs)
                : null
        try {
            await handler(job)
        } catch (err) {
            // The handler is expected to release the job on its own error paths.
            // If it threw without releasing, the row stays in `running` with our
            // `lock_id` set — the janitor's stall reaper will catch it via
            // `stallTimeoutMs`. We log here so failures aren't silent.
            logger.error({ err, sessionId: job.id }, 'SessionQueueWorker handler threw')
        } finally {
            if (hb) {
                clearInterval(hb)
            }
            this.inFlight--
            this.signalSlotFreed()
        }
    }

    private waitForSlot(): Promise<void> {
        return new Promise<void>((resolve) => {
            this.slotWakers.push(resolve)
        })
    }

    /** Wake exactly one parked fetcher iteration. No-op if none are waiting. */
    private signalSlotFreed(): void {
        const waker = this.slotWakers.shift()
        if (waker) {
            waker()
        }
    }

    private async dequeueJobs(limit: number): Promise<RawSessionRow[]> {
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
                agent_sessions.lock_id,
                agent_sessions.principal`,
            [this.config.queueName, limit, lockId]
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
            principal: row.principal ?? null,

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
        if (!this.isConsuming) {
            return false
        }
        // In-flight handlers count as healthy — the fetcher legitimately parks
        // on `waitForSlot()` when all slots are full, which would otherwise
        // make `lastTickTime` stale even though work is happening.
        if (this.inFlight > 0) {
            return true
        }
        return Date.now() - this.lastTickTime.getTime() < this.heartbeatTimeoutMs
    }

    /** For tests: read-only view of the in-flight count. */
    get inFlightCount(): number {
        return this.inFlight
    }

    async stopConsuming(): Promise<void> {
        this.isConsuming = false
        // Wake every parked fetcher iteration so the loop sees `!isConsuming` and exits.
        const wakers = this.slotWakers
        this.slotWakers = []
        for (const w of wakers) {
            w()
        }
        if (this.fetcherLoopPromise) {
            await this.fetcherLoopPromise
            this.fetcherLoopPromise = null
        }
    }

    async disconnect(): Promise<void> {
        await this.stopConsuming()
        if (this.activeJobs.size > 0) {
            const drain = Promise.all(Array.from(this.activeJobs))
            await Promise.race([drain, sleep(this.drainTimeoutMs)])
        }
        await this.pool.end()
    }
}

function sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms))
}
