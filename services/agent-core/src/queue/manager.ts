import type { Principal } from '@repo/ass-server/types'
import { Pool } from 'pg'
import { v7 as uuidv7 } from 'uuid'

import { logger } from '../logger'
import { createAgentPgPool } from '../postgres'
import { ManagerConfig, SessionJobInit, SessionJobInitSchema } from './types'

const DEFAULT_DEPTH_LIMIT = 1_000_000
const DEFAULT_DEPTH_CHECK_INTERVAL_MS = 10_000
const DEFAULT_MAX_STATE_BYTES = 1_048_576 // 1 MiB soft cap

export class SessionQueueManager {
    private pool: Pool
    private readonly depthLimit: number
    private readonly depthCheckIntervalMs: number
    private readonly maxStateByteSize: number
    private depthCheckPromise: Promise<boolean> | null = null
    private depthCheckExpiresAt = 0

    constructor(config: ManagerConfig) {
        this.pool = createAgentPgPool(config.pool, 10)
        this.depthLimit = config.depthLimit ?? DEFAULT_DEPTH_LIMIT
        this.depthCheckIntervalMs = config.depthCheckIntervalMs ?? DEFAULT_DEPTH_CHECK_INTERVAL_MS
        this.maxStateByteSize = config.maxStateByteSize ?? DEFAULT_MAX_STATE_BYTES
    }

    async connect(): Promise<void> {
        const client = await this.pool.connect()
        client.release()
    }

    async createJob(input: SessionJobInit): Promise<string> {
        const job = SessionJobInitSchema.parse(input)
        this.assertStateUnderCap(job.state)
        await this.insertGuard()

        const id = job.id ?? uuidv7()
        const now = new Date()
        const stateByteSize = job.state ? job.state.byteLength : null
        // Stringify here rather than relying on pg's JSON serialization so
        // an explicit `null` lands as SQL NULL (not the JSON literal `null`).
        const principalJson = input.principal ? JSON.stringify(input.principal) : null

        await this.pool.query(
            `INSERT INTO agent_sessions
             (id, team_id, application_id, revision_id, queue_name, status, scheduled, created,
              lock_id, last_heartbeat, janitor_touch_count, transition_count, last_transition,
              state, state_byte_size, principal, external_key)
             VALUES ($1, $2, $3, $4, $5, 'available', $6, $7,
                     NULL, NULL, 0, 0, $7,
                     $8, $9, $10::jsonb, $11)`,
            [
                id,
                job.teamId,
                job.applicationId ?? null,
                job.revisionId ?? null,
                job.queueName,
                job.scheduled ?? now,
                now,
                job.state ?? null,
                stateByteSize,
                principalJson,
                job.externalKey ?? null,
            ]
        )
        return id
    }

    /**
     * Resolve `(team, application, external_key)` to an active session
     * id. Used by ingress when a trigger emits an `externalKey` — a
     * second Slack `app_mention` in the same thread, an email reply,
     * any future webhook follow-up — to route it as `/send` into an
     * existing session rather than spawning a new one.
     *
     * Returns `null` when no active session exists; the caller then
     * enqueues a new one. Terminal sessions are deliberately ignored
     * so a closed thread doesn't pin its successor forever.
     */
    async findActiveSessionByExternalKey(
        teamId: number,
        applicationId: string,
        externalKey: string
    ): Promise<string | null> {
        const { rows } = await this.pool.query<{ id: string }>(
            `SELECT id::text AS id
             FROM agent_sessions
             WHERE team_id = $1
               AND application_id = $2
               AND external_key = $3
               AND status IN ('available', 'running')
             ORDER BY created DESC
             LIMIT 1`,
            [teamId, applicationId, externalKey]
        )
        return rows[0]?.id ?? null
    }

    /**
     * Read the principal stamped on a session at creation, if any. Used by
     * agent-ingress on `/listen` / `/send` / `/cancel` to strict-match the
     * re-resolved caller. Returns `null` for a session created without one
     * (e.g. an `auth: public` agent), or `undefined` if the session id
     * doesn't exist — callers distinguish "no principal" from "no session"
     * via this trit.
     */
    async getPrincipal(sessionId: string): Promise<Principal | null | undefined> {
        const { rows } = await this.pool.query<{ principal: Principal | null }>(
            `SELECT principal FROM agent_sessions WHERE id = $1`,
            [sessionId]
        )
        if (rows.length === 0) {
            return undefined
        }
        return rows[0].principal
    }

    /**
     * Result of trying to durably accept a `/send/:id` payload.
     *
     *   - `accepted`: appended to `pending_inputs`; `status` reflects the
     *     row's pre-update status. If it was `available` and parked in the
     *     future, the call also advances `scheduled` to NOW so the worker
     *     picks the job up immediately.
     *   - `terminal`: the session has already ended (completed / failed /
     *     canceled). Ingress should return 410 Gone — never 202.
     *   - `not_found`: no such session id. Ingress returns 404.
     */
    async appendPendingInput(
        sessionId: string,
        content: string
    ): Promise<{ kind: 'accepted'; status: 'available' | 'running' } | { kind: 'terminal' } | { kind: 'not_found' }> {
        const at = new Date().toISOString()
        // jsonb_insert at the end of the array is the idiomatic "append";
        // `jsonb || jsonb` would also work but jsonb_insert preserves
        // existing-element identity and emits a clearer plan. Wrap in a
        // single UPDATE so an /send and the worker's state write touch
        // disjoint columns and never race.
        //
        // Advancing `scheduled` to NOW when status is `available` wakes
        // a parked job (one whose scheduled_at was pushed into the future
        // by the worker after an `awaiting_input` outcome). Running jobs
        // ignore the new value — their lease covers the current turn.
        const { rows } = await this.pool.query<{
            status: 'available' | 'running' | 'completed' | 'failed' | 'canceled'
        }>(
            `UPDATE agent_sessions
             SET pending_inputs = pending_inputs || $2::jsonb,
                 scheduled = CASE WHEN status = 'available' THEN NOW() ELSE scheduled END
             WHERE id = $1
             RETURNING status`,
            [sessionId, JSON.stringify([{ at, content }])]
        )
        if (rows.length === 0) {
            return { kind: 'not_found' }
        }
        const status = rows[0].status
        if (status === 'completed' || status === 'failed' || status === 'canceled') {
            // Roll back the append — we don't want pending_inputs growing
            // on a dead session. A failed UPDATE here is a no-op (the row
            // is terminal anyway); ignore errors.
            await this.pool
                .query(
                    `UPDATE agent_sessions
                     SET pending_inputs = (
                       SELECT COALESCE(jsonb_agg(elem), '[]'::jsonb)
                       FROM jsonb_array_elements(pending_inputs) elem
                       WHERE elem ->> 'at' <> $2 OR elem ->> 'content' <> $3
                     )
                     WHERE id = $1`,
                    [sessionId, at, content]
                )
                .catch(() => {
                    /* best-effort rollback */
                })
            return { kind: 'terminal' }
        }
        return { kind: 'accepted', status }
    }

    /**
     * Cancel a parked session directly. Used by ingress when a client
     * calls `/cancel/:id` on a session whose worker isn't holding the
     * lock (status='available') — bus-published cancels only reach a
     * running executor. Returns:
     *
     *   - `canceled`: the row was available; we flipped it to
     *     `canceled` ourselves.
     *   - `running`: the row is locked by a worker; the bus path is
     *     the right one. Ingress should fall through to publishInput.
     *   - `terminal`: already at a terminal status — nothing to do.
     *   - `not_found`: no such session id.
     */
    async cancelIfParked(sessionId: string): Promise<'canceled' | 'running' | 'terminal' | 'not_found'> {
        const { rows } = await this.pool.query<{
            status: 'available' | 'running' | 'completed' | 'failed' | 'canceled'
            updated: boolean
        }>(
            `WITH probe AS (
                SELECT status FROM agent_sessions WHERE id = $1 FOR UPDATE
             ), updated AS (
                UPDATE agent_sessions
                SET status = 'canceled',
                    last_transition = NOW(),
                    transition_count = transition_count + 1
                WHERE id = $1 AND status = 'available'
                RETURNING 1
             )
             SELECT probe.status, EXISTS(SELECT 1 FROM updated) AS updated FROM probe`,
            [sessionId]
        )
        if (rows.length === 0) {
            return 'not_found'
        }
        if (rows[0].updated) {
            return 'canceled'
        }
        if (rows[0].status === 'running') {
            return 'running'
        }
        return 'terminal'
    }

    async disconnect(): Promise<void> {
        await this.pool.end()
    }

    private assertStateUnderCap(state: Buffer | null | undefined): void {
        if (state && state.byteLength > this.maxStateByteSize) {
            throw new Error(
                `Session state too large (${state.byteLength} bytes, cap ${this.maxStateByteSize}); ` +
                    'offload conversation log to S3 and store only the pointer in state.'
            )
        }
    }

    private async insertGuard(): Promise<void> {
        if (await this.isFull()) {
            throw new Error(`Agent session queue is full (depth limit: ${this.depthLimit})`)
        }
    }

    private isFull(): Promise<boolean> {
        if (this.depthCheckPromise && Date.now() < this.depthCheckExpiresAt) {
            return this.depthCheckPromise
        }
        this.depthCheckPromise = this.queryDepth()
        this.depthCheckExpiresAt = Date.now() + this.depthCheckIntervalMs
        return this.depthCheckPromise
    }

    private async queryDepth(): Promise<boolean> {
        try {
            const result = await this.pool.query<{ count: string }>(
                `SELECT COUNT(*) AS count FROM agent_sessions
                 WHERE status = 'available' AND scheduled <= NOW()`
            )
            const count = parseInt(result.rows[0].count, 10)
            const full = count >= this.depthLimit
            if (full) {
                logger.warn('Agent session queue at capacity', { count, depthLimit: this.depthLimit })
            }
            return full
        } catch (e) {
            logger.error('Agent session queue depth check failed', { error: String(e) })
            return false
        }
    }
}
