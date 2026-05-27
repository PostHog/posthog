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
    /**
     * `/send`-delivered messages waiting at the time of this dequeue.
     * Atomically drained (set to '[]') by the dequeue UPDATE; the
     * captured pre-update value rides through to the handler. Any
     * `/send` arriving DURING the turn lands on the now-empty column
     * and is visible to the worker's NEXT dequeue.
     */
    drained_inputs: Array<{ at: string; content: string }>
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
        // SNAPSHOT (not drain) pending_inputs at dequeue. The worker
        // sees what's queued; subsequent /send appends land in the
        // same column. The turn-commit path (reschedule / ack / fail /
        // cancel) is responsible for filtering out the snapshotted
        // entries by their `at` timestamp — at-least-once semantics.
        //
        // Why not drain here: a worker dying mid-turn would otherwise
        // lose the drained /sends forever. With snapshot-only, an
        // orphaned dequeue (status=running, lock_id mismatch on
        // commit) leaves pending_inputs intact and the NEXT dequeue
        // sees the same messages again. Duplicate-delivery is the
        // tradeoff; the chat agents can absorb that (state.messages
        // is deduplicated by content+at at the executor level).
        const result = await this.pool.query<RawSessionRow>(
            `WITH available AS (
                SELECT id, pending_inputs
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
                agent_sessions.principal,
                available.pending_inputs AS drained_inputs`,
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
            drainedInputs: row.drained_inputs ?? [],

            async ack(options?: TurnCommitOptions): Promise<void> {
                releaseGuard('ack')
                await commitTurn(pool, row.id, lockId, 'completed', options)
            },

            async fail(options?: TurnCommitOptions): Promise<void> {
                releaseGuard('fail')
                await commitTurn(pool, row.id, lockId, 'failed', options)
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
                if (options?.drainedInputAts && options.drainedInputAts.length > 0) {
                    params.push(options.drainedInputAts)
                    setClauses.push(
                        `pending_inputs = COALESCE(
                            (SELECT jsonb_agg(elem)
                             FROM jsonb_array_elements(pending_inputs) elem
                             WHERE NOT (elem ->> 'at' = ANY($${params.length}::text[]))),
                            '[]'::jsonb
                         )`
                    )
                }
                await pool.query(
                    `UPDATE agent_sessions SET ${setClauses.join(', ')}
                     WHERE id = $1 AND lock_id = $2`,
                    params
                )
            },

            async cancel(options?: TurnCommitOptions): Promise<void> {
                releaseGuard('cancel')
                await commitTurn(pool, row.id, lockId, 'canceled', options)
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

    /**
     * Peek at `pending_inputs` for entries the worker HASN'T already
     * consumed this turn. Used by the agent-runner's turn loop to
     * decide whether parking after `awaiting_input` should sleep
     * (nothing new queued) or wake immediately (a `/send` mid-turn
     * already left a message that couldn't advance `scheduled`
     * because status was 'running').
     *
     * Passing `excludeAts` filters out the snapshot the worker took
     * at dequeue — anything left over arrived AFTER and needs a turn.
     */
    async hasPendingInputs(sessionId: string, excludeAts: string[] = []): Promise<boolean> {
        const { rows } = await this.pool.query<{ has: boolean }>(
            `SELECT EXISTS (
                SELECT 1 FROM jsonb_array_elements(pending_inputs) elem
                WHERE NOT (elem ->> 'at' = ANY($2::text[]))
             ) AS has
             FROM agent_sessions WHERE id = $1`,
            [sessionId, excludeAts]
        )
        return rows[0]?.has === true
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

/**
 * Options accepted by the terminal-state transitions (ack/fail/cancel)
 * AND the parked-state transition (reschedule via RescheduleOptions).
 * Carries the final state write plus the list of pending-input `at`
 * timestamps the worker drained during this turn — used to filter
 * the pending_inputs column atomically with the commit.
 */
export interface TurnCommitOptions {
    state?: Buffer | null
    /**
     * `at` timestamps of the pending-input entries the worker consumed
     * during this turn. The commit UPDATE removes only these from
     * pending_inputs, leaving any /send that arrived mid-turn intact
     * for the next dequeue. Omitting clears nothing — used by ack/
     * fail/cancel on sessions that never had queued input.
     */
    drainedInputAts?: string[]
}

async function commitTurn(
    pool: Pool,
    sessionId: string,
    lockId: string,
    status: 'completed' | 'failed' | 'canceled',
    options?: TurnCommitOptions
): Promise<void> {
    const setParts = [
        `status = '${status}'`,
        `lock_id = NULL`,
        `last_heartbeat = NULL`,
        `last_transition = NOW()`,
        `transition_count = transition_count + 1`,
    ]
    const params: unknown[] = [sessionId, lockId]
    if (options && 'state' in options) {
        params.push(options.state ?? null)
        setParts.push(`state = $${params.length}`)
        params.push(options.state ? options.state.byteLength : null)
        setParts.push(`state_byte_size = $${params.length}`)
    }
    if (options?.drainedInputAts && options.drainedInputAts.length > 0) {
        params.push(options.drainedInputAts)
        setParts.push(
            `pending_inputs = COALESCE(
                (SELECT jsonb_agg(elem)
                 FROM jsonb_array_elements(pending_inputs) elem
                 WHERE NOT (elem ->> 'at' = ANY($${params.length}::text[]))),
                '[]'::jsonb
             )`
        )
    }
    await pool.query(
        `UPDATE agent_sessions
         SET ${setParts.join(', ')}
         WHERE id = $1 AND lock_id = $2`,
        params
    )
}
