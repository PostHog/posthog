import { DateTime } from 'luxon'
import { Pool } from 'pg'

import { createAgentPgPool } from '../postgres'
import { PoolConfig, SessionStatus } from './types'

export interface SessionView {
    readonly id: string
    readonly teamId: number
    readonly applicationId: string | null
    readonly revisionId: string | null
    readonly queueName: string
    readonly status: SessionStatus
    readonly scheduled: DateTime
    readonly created: DateTime
    readonly lastTransition: DateTime
    readonly lastHeartbeat: DateTime | null
    readonly transitionCount: number
    readonly janitorTouchCount: number
    readonly stateByteSize: number | null
}

export interface ListSessionsFilter {
    teamId?: number
    applicationId?: string
    revisionId?: string
    status?: SessionStatus | readonly SessionStatus[]
    /** Strict upper bound on `created`; for keyset pagination. */
    createdBefore?: Date
    limit?: number
}

interface RawSessionRow {
    id: string
    team_id: number
    application_id: string | null
    revision_id: string | null
    queue_name: string
    status: SessionStatus
    scheduled: string
    created: string
    last_transition: string
    last_heartbeat: string | null
    transition_count: number
    janitor_touch_count: number
    state_byte_size: number | null
}

const DEFAULT_LIMIT = 50
const MAX_LIMIT = 200

const STATUSES: readonly SessionStatus[] = ['available', 'running', 'completed', 'failed', 'canceled']

/**
 * Read-only + targeted-write queries over the agent_sessions queue.
 *
 * Worker / manager / janitor handle the lifecycle transitions; this is the surface
 * the operational HTTP endpoints (Django → runtime internal API) use to render
 * session lists and to cancel an in-flight session.
 *
 * Distinct from the worker dequeue path — these queries never lock rows.
 */
export class SessionQuery {
    private readonly pool: Pool

    constructor(config: { pool: PoolConfig }) {
        this.pool = createAgentPgPool(config.pool, 5)
    }

    async connect(): Promise<void> {
        const client = await this.pool.connect()
        client.release()
    }

    async disconnect(): Promise<void> {
        await this.pool.end()
    }

    async findSession(id: string): Promise<SessionView | null> {
        const result = await this.pool.query<RawSessionRow>(
            `SELECT id, team_id, application_id, revision_id, queue_name, status,
                    scheduled, created, last_transition, last_heartbeat,
                    transition_count, janitor_touch_count, state_byte_size
             FROM agent_sessions
             WHERE id = $1`,
            [id]
        )
        if (result.rows.length === 0) {
            return null
        }
        return rowToView(result.rows[0])
    }

    async listSessions(filter: ListSessionsFilter = {}): Promise<SessionView[]> {
        const where: string[] = []
        const params: unknown[] = []
        const push = (clause: string, value: unknown): void => {
            params.push(value)
            where.push(clause.replace('?', `$${params.length}`))
        }
        if (filter.teamId !== undefined) {
            push('team_id = ?', filter.teamId)
        }
        if (filter.applicationId) {
            push('application_id = ?', filter.applicationId)
        }
        if (filter.revisionId) {
            push('revision_id = ?', filter.revisionId)
        }
        if (filter.status) {
            const statuses = normalizeStatuses(filter.status)
            push('status = ANY(?::AgentSessionStatus[])', statuses)
        }
        if (filter.createdBefore) {
            push('created < ?', filter.createdBefore)
        }

        const limit = clampLimit(filter.limit)
        params.push(limit)

        const result = await this.pool.query<RawSessionRow>(
            `SELECT id, team_id, application_id, revision_id, queue_name, status,
                    scheduled, created, last_transition, last_heartbeat,
                    transition_count, janitor_touch_count, state_byte_size
             FROM agent_sessions
             ${where.length > 0 ? `WHERE ${where.join(' AND ')}` : ''}
             ORDER BY created DESC
             LIMIT $${params.length}`,
            params
        )
        return result.rows.map(rowToView)
    }

    /**
     * Cancel a session that hasn't reached a terminal state yet. Returns the resulting
     * view (or `null` if no row matches) so the caller can distinguish "already terminal"
     * from "doesn't exist".
     */
    async cancelSession(id: string): Promise<SessionView | null> {
        const result = await this.pool.query<RawSessionRow>(
            `UPDATE agent_sessions
             SET status = 'canceled',
                 lock_id = NULL,
                 last_heartbeat = NULL,
                 last_transition = NOW(),
                 transition_count = transition_count + 1
             WHERE id = $1
               AND status IN ('available', 'running')
             RETURNING id, team_id, application_id, revision_id, queue_name, status,
                       scheduled, created, last_transition, last_heartbeat,
                       transition_count, janitor_touch_count, state_byte_size`,
            [id]
        )
        if (result.rows.length > 0) {
            return rowToView(result.rows[0])
        }
        return this.findSession(id)
    }
}

function rowToView(row: RawSessionRow): SessionView {
    return {
        id: row.id,
        teamId: row.team_id,
        applicationId: row.application_id,
        revisionId: row.revision_id,
        queueName: row.queue_name,
        status: row.status,
        scheduled: DateTime.fromISO(row.scheduled, { zone: 'utc' }),
        created: DateTime.fromISO(row.created, { zone: 'utc' }),
        lastTransition: DateTime.fromISO(row.last_transition, { zone: 'utc' }),
        lastHeartbeat: row.last_heartbeat ? DateTime.fromISO(row.last_heartbeat, { zone: 'utc' }) : null,
        transitionCount: row.transition_count,
        janitorTouchCount: row.janitor_touch_count,
        stateByteSize: row.state_byte_size,
    }
}

function normalizeStatuses(input: SessionStatus | readonly SessionStatus[]): SessionStatus[] {
    const asArray = Array.isArray(input) ? input : [input as SessionStatus]
    for (const s of asArray) {
        if (!STATUSES.includes(s)) {
            throw new Error(`SessionQuery: unknown status filter: ${s}`)
        }
    }
    return asArray as SessionStatus[]
}

function clampLimit(limit: number | undefined): number {
    if (limit === undefined) {
        return DEFAULT_LIMIT
    }
    if (!Number.isInteger(limit) || limit <= 0) {
        return DEFAULT_LIMIT
    }
    return Math.min(limit, MAX_LIMIT)
}
