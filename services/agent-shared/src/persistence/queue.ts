/**
 * Session queue contract. v2 uses Postgres-backed queueing (one row per
 * AgentSession, claimable via SELECT FOR UPDATE SKIP LOCKED). Tests use the
 * in-memory impl below.
 */

import { AgentSession, ConversationMessage } from '../spec/spec'

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
    get(sessionId: string): Promise<AgentSession | null>
    /** Find an existing session matching (application_id, external_key). */
    findByExternalKey(applicationId: string, externalKey: string): Promise<AgentSession | null>
    /**
     * List sessions for one application, newest first. `limit` defaults to 100
     * so a buggy caller can't accidentally page through every session in the
     * project; supply an explicit larger value if needed (capped at 500
     * server-side). Filters compose with AND semantics.
     */
    listByApplication(applicationId: string, opts?: ListSessionsOpts): Promise<AgentSession[]>
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

    async get(sessionId: string): Promise<AgentSession | null> {
        return this.sessions.get(sessionId) ?? null
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
        const stateSet = opts.states && opts.states.length > 0 ? new Set(opts.states) : null
        const matches = [...this.sessions.values()].filter((s) => {
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
        matches.sort((a, b) => b.created_at.localeCompare(a.created_at))
        return matches.slice(offset, offset + limit)
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
