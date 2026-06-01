/**
 * Session queue contract. v2 uses Postgres-backed queueing (one row per
 * AgentSession, claimable via SELECT FOR UPDATE SKIP LOCKED). Tests use the
 * in-memory impl below.
 */

import { AgentSession, ConversationMessage, PendingElevationRequest } from '../spec/spec'

/** Shape returned by both `aggregateForApplication` and `aggregateForTeam`. */
export interface AggregateStats {
    /** Sessions currently in a live state (queued / running / waiting). */
    liveCount: number
    /** Sessions created within the `since` window — all states. */
    sessionsInWindowCount: number
    /** Sum of `usage_total.cost_total` across sessions in the window. */
    spendInWindowUsd: number
    /** ISO timestamp of the most recent session update — null if none. */
    lastActivityAt: string | null
    /** Sessions in `failed` state created within the window. */
    failedInWindowCount: number
}

/** Live (non-terminal) session states. `completed`/`closed`/`cancelled`/`failed` are terminal. */
export const LIVE_SESSION_STATES: AgentSession['state'][] = ['queued', 'running']

export interface ListSessionsOpts {
    limit?: number
    offset?: number
    /** Filter to one or more session states (e.g. ['completed','failed']). */
    states?: AgentSession['state'][]
    /** Filter to a specific revision id within the application. */
    revisionId?: string
    /** ISO datetime — only return sessions with created_at >= this. */
    createdAfter?: string
    /** ISO datetime — only return sessions with created_at <= this. */
    createdBefore?: string
}

export interface SessionQueue {
    enqueue(session: AgentSession): Promise<void>
    /** Block-claim the next session, returning null if none available within timeoutMs. */
    claim(timeoutMs: number): Promise<AgentSession | null>
    update(sessionId: string, patch: Partial<AgentSession>): Promise<void>
    /**
     * Append a message into a session. By default routes into `pending_inputs`
     * so it doesn't contend with an in-flight turn. The runner drains
     * pending_inputs into `conversation` at the start of each turn.
     */
    appendPendingInput(sessionId: string, msg: ConversationMessage): Promise<void>
    /** Append directly into `conversation` (runner-side use only). */
    appendConversation(sessionId: string, msg: ConversationMessage): Promise<void>
    /**
     * Append a pending elevation request to the session. Used by ingress when
     * `requireAclAccess` rejects an incoming principal — the rejected message
     * is preserved so a future grant can replay it.
     */
    appendPendingElevationRequest(sessionId: string, req: PendingElevationRequest): Promise<void>
    get(sessionId: string): Promise<AgentSession | null>
    /** Find an existing session matching (application_id, external_key). */
    findByExternalKey(applicationId: string, externalKey: string): Promise<AgentSession | null>
    /**
     * Find an existing session matching (application_id, idempotency_key).
     * Returns null if no row exists (including when the key was nulled by the
     * 30-day retention sweep). Semantically distinct from
     * `findByExternalKey`: a hit here means "this exact request was already
     * accepted" — the caller returns the existing session id without
     * appending or resuming. See `cron-trigger-scheduler.md` §6.
     */
    findByIdempotencyKey(applicationId: string, idempotencyKey: string): Promise<AgentSession | null>
    /**
     * Null out `idempotency_key` on sessions older than `cutoff`. The
     * platform-wide janitor sweep runs this on a 30-day retention to keep
     * the partial unique index compact — by that point any retry that
     * would have collided has long since happened. Returns the count of
     * rows updated. Plan `cron-trigger-scheduler.md` §6 "Retention."
     */
    clearStaleIdempotencyKeys(cutoff: Date): Promise<number>
    /**
     * List sessions for one application, newest first. `limit` defaults to 100
     * so a buggy caller can't accidentally page through every session in the
     * project; supply an explicit larger value if needed (capped at 500
     * server-side). Filters compose with AND semantics.
     */
    listByApplication(applicationId: string, opts?: ListSessionsOpts): Promise<AgentSession[]>
    /**
     * Count sessions matching the same filters as `listByApplication`. Used
     * by paginated callers (the janitor wraps `{ results, count }`). `limit`
     * and `offset` are ignored — the count is over the full filtered set.
     */
    countByApplication(applicationId: string, opts?: Omit<ListSessionsOpts, 'limit' | 'offset'>): Promise<number>
    /**
     * Roll up summary stats for an agent — drives the agent-detail
     * overview tiles. `since` filters cost + sessions count to a
     * trailing window (e.g. 24h). `liveCount` is independent of
     * `since`. `lastActivityAt` is the most recent `updated_at`
     * across all states (null when the agent has no sessions).
     */
    aggregateForApplication(applicationId: string, since: string): Promise<AggregateStats>
    /**
     * Same shape as `aggregateForApplication`, scoped to every agent
     * owned by a team. Drives the fleet-stats tile on the agents list.
     */
    aggregateForTeam(teamId: number, since: string): Promise<AggregateStats>
    /**
     * All sessions for a team currently in a live state — queued,
     * running, waiting. Drives the live-sessions panel. Capped at
     * `limit` (default 100) so a single call can't accidentally page
     * every session.
     */
    listLiveForTeam(teamId: number, opts?: { limit?: number }): Promise<AgentSession[]>
    /**
     * Re-queue sessions stuck in 'running' beyond the TTL (their worker
     * probably crashed). The session's conversation is preserved; a sibling
     * worker picks it up via the normal claim path.
     *
     * Poison-pill semantics: increments `retry_count` on every reap. Sessions
     * whose retry_count would exceed `maxRetries` are marked `failed` instead
     * of re-queued — a genuinely broken job (e.g. consistently crashes the
     * worker) won't loop forever.
     *
     * Returns `{ requeued, poisoned }` so the janitor can report both.
     */
    reapStuckRunning(thresholdMs: number, maxRetries: number): Promise<{ requeued: number; poisoned: number }>
    /**
     * Idle `completed` sessions whose `updated_at` is older than the floor
     * threshold. The sweep consumes this list and applies per-agent TTL
     * before deciding to close — `floorMaxAgeMs` is the platform-wide
     * default, sessions with an opt-in `spec.resume.max_completed_age_ms`
     * may still be retained.
     */
    listIdleCompleted(floorMaxAgeMs: number, limit?: number): Promise<AgentSession[]>
}

/** In-memory test impl. Not thread-safe across processes. */
export class MemorySessionQueue implements SessionQueue {
    private readonly sessions = new Map<string, AgentSession>()
    private readonly waiting: string[] = []

    async enqueue(session: AgentSession): Promise<void> {
        this.sessions.set(session.id, session)
        this.waiting.push(session.id)
    }

    async claim(_timeoutMs: number): Promise<AgentSession | null> {
        const id = this.waiting.shift()
        if (!id) {
            return null
        }
        const s = this.sessions.get(id)
        if (!s) {
            return null
        }
        s.state = 'running'
        s.updated_at = new Date().toISOString()
        return s
    }

    async update(sessionId: string, patch: Partial<AgentSession>): Promise<void> {
        const s = this.sessions.get(sessionId)
        if (!s) {
            return
        }
        Object.assign(s, patch, { updated_at: new Date().toISOString() })
    }

    async appendPendingInput(sessionId: string, msg: ConversationMessage): Promise<void> {
        const s = this.sessions.get(sessionId)
        if (!s) {
            return
        }
        s.pending_inputs.push(msg)
        s.updated_at = new Date().toISOString()
    }

    async appendConversation(sessionId: string, msg: ConversationMessage): Promise<void> {
        const s = this.sessions.get(sessionId)
        if (!s) {
            return
        }
        s.conversation.push(msg)
        s.updated_at = new Date().toISOString()
    }

    async appendPendingElevationRequest(sessionId: string, req: PendingElevationRequest): Promise<void> {
        const s = this.sessions.get(sessionId)
        if (!s) {
            return
        }
        s.pending_elevation_requests.push(req)
        s.updated_at = new Date().toISOString()
    }

    async get(sessionId: string): Promise<AgentSession | null> {
        return this.sessions.get(sessionId) ?? null
    }

    async findByIdempotencyKey(applicationId: string, idempotencyKey: string): Promise<AgentSession | null> {
        for (const s of this.sessions.values()) {
            if (s.application_id === applicationId && s.idempotency_key === idempotencyKey) {
                return s
            }
        }
        return null
    }

    async clearStaleIdempotencyKeys(cutoff: Date): Promise<number> {
        let cleared = 0
        for (const s of this.sessions.values()) {
            if (s.idempotency_key === null) {
                continue
            }
            const created = Date.parse(s.created_at)
            if (Number.isFinite(created) && created < cutoff.getTime()) {
                s.idempotency_key = null
                cleared++
            }
        }
        return cleared
    }

    async findByExternalKey(applicationId: string, externalKey: string): Promise<AgentSession | null> {
        for (const s of this.sessions.values()) {
            if (s.application_id === applicationId && s.external_key === externalKey) {
                return s
            }
        }
        return null
    }

    async listByApplication(applicationId: string, opts: ListSessionsOpts = {}): Promise<AgentSession[]> {
        const limit = opts.limit ?? 100
        const offset = opts.offset ?? 0
        const matches = this.filteredSessions(applicationId, opts)
        matches.sort((a, b) => b.created_at.localeCompare(a.created_at))
        return matches.slice(offset, offset + limit)
    }

    async countByApplication(
        applicationId: string,
        opts: Omit<ListSessionsOpts, 'limit' | 'offset'> = {}
    ): Promise<number> {
        return this.filteredSessions(applicationId, opts).length
    }

    private filteredSessions(applicationId: string, opts: Omit<ListSessionsOpts, 'limit' | 'offset'>): AgentSession[] {
        const stateSet = opts.states && opts.states.length > 0 ? new Set(opts.states) : null
        return [...this.sessions.values()].filter((s) => {
            if (s.application_id !== applicationId) {
                return false
            }
            if (stateSet && !stateSet.has(s.state)) {
                return false
            }
            if (opts.revisionId && s.revision_id !== opts.revisionId) {
                return false
            }
            if (opts.createdAfter && s.created_at < opts.createdAfter) {
                return false
            }
            if (opts.createdBefore && s.created_at > opts.createdBefore) {
                return false
            }
            return true
        })
    }

    async listIdleCompleted(floorMaxAgeMs: number, limit = 200): Promise<AgentSession[]> {
        const cutoff = Date.now() - floorMaxAgeMs
        const matches: AgentSession[] = []
        for (const s of this.sessions.values()) {
            if (s.state !== 'completed') {
                continue
            }
            const updated = Date.parse(s.updated_at)
            if (!Number.isFinite(updated) || updated >= cutoff) {
                continue
            }
            matches.push(s)
            if (matches.length >= limit) {
                break
            }
        }
        return matches
    }

    async aggregateForApplication(applicationId: string, since: string): Promise<AggregateStats> {
        const liveSet = new Set<AgentSession['state']>(LIVE_SESSION_STATES)
        let liveCount = 0
        let sessionsInWindowCount = 0
        let spendInWindowUsd = 0
        let failedInWindowCount = 0
        let lastActivityAt: string | null = null
        for (const s of this.sessions.values()) {
            if (s.application_id !== applicationId) {
                continue
            }
            if (!lastActivityAt || s.updated_at > lastActivityAt) {
                lastActivityAt = s.updated_at
            }
            if (liveSet.has(s.state)) {
                liveCount++
            }
            if (s.created_at >= since) {
                sessionsInWindowCount++
                spendInWindowUsd += s.usage_total?.cost_total ?? 0
                if (s.state === 'failed') {
                    failedInWindowCount++
                }
            }
        }
        return { liveCount, sessionsInWindowCount, spendInWindowUsd, lastActivityAt, failedInWindowCount }
    }

    async aggregateForTeam(teamId: number, since: string): Promise<AggregateStats> {
        const liveSet = new Set<AgentSession['state']>(LIVE_SESSION_STATES)
        let liveCount = 0
        let sessionsInWindowCount = 0
        let spendInWindowUsd = 0
        let failedInWindowCount = 0
        let lastActivityAt: string | null = null
        for (const s of this.sessions.values()) {
            if (s.team_id !== teamId) {
                continue
            }
            if (!lastActivityAt || s.updated_at > lastActivityAt) {
                lastActivityAt = s.updated_at
            }
            if (liveSet.has(s.state)) {
                liveCount++
            }
            if (s.created_at >= since) {
                sessionsInWindowCount++
                spendInWindowUsd += s.usage_total?.cost_total ?? 0
                if (s.state === 'failed') {
                    failedInWindowCount++
                }
            }
        }
        return { liveCount, sessionsInWindowCount, spendInWindowUsd, lastActivityAt, failedInWindowCount }
    }

    async listLiveForTeam(teamId: number, opts: { limit?: number } = {}): Promise<AgentSession[]> {
        const limit = Math.max(1, Math.min(opts.limit ?? 100, 500))
        const liveSet = new Set<AgentSession['state']>(LIVE_SESSION_STATES)
        const matches = [...this.sessions.values()].filter((s) => s.team_id === teamId && liveSet.has(s.state))
        matches.sort((a, b) => b.updated_at.localeCompare(a.updated_at))
        return matches.slice(0, limit)
    }

    async reapStuckRunning(thresholdMs: number, maxRetries: number): Promise<{ requeued: number; poisoned: number }> {
        const cutoff = Date.now() - thresholdMs
        let requeued = 0
        let poisoned = 0
        for (const s of this.sessions.values()) {
            if (s.state !== 'running') {
                continue
            }
            const updated = Date.parse(s.updated_at)
            if (!Number.isFinite(updated) || updated >= cutoff) {
                continue
            }
            const nextRetry = (s.retry_count ?? 0) + 1
            if (nextRetry > maxRetries) {
                s.state = 'failed'
                s.retry_count = nextRetry
                s.updated_at = new Date().toISOString()
                poisoned++
                continue
            }
            s.state = 'queued'
            s.retry_count = nextRetry
            s.updated_at = new Date().toISOString()
            this.waiting.push(s.id)
            requeued++
        }
        return { requeued, poisoned }
    }

    /** Test helper. */
    requeue(sessionId: string): void {
        this.waiting.push(sessionId)
    }
}
