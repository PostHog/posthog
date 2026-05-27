/**
 * Session queue contract. v2 uses Postgres-backed queueing (one row per
 * AgentSession, claimable via SELECT FOR UPDATE SKIP LOCKED). Tests use the
 * in-memory impl below.
 */

import { AgentSession, ConversationMessage } from './spec'

export interface SessionQueue {
    enqueue(session: AgentSession): Promise<void>
    /** Block-claim the next session, returning null if none available within timeoutMs. */
    claim(timeoutMs: number): Promise<AgentSession | null>
    update(sessionId: string, patch: Partial<AgentSession>): Promise<void>
    appendMessage(sessionId: string, msg: ConversationMessage): Promise<void>
    get(sessionId: string): Promise<AgentSession | null>
    /** Find an existing session matching (application_id, external_key). */
    findByExternalKey(applicationId: string, externalKey: string): Promise<AgentSession | null>
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

    async appendMessage(sessionId: string, msg: ConversationMessage): Promise<void> {
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

    /** Test helper. */
    requeue(sessionId: string): void {
        this.waiting.push(sessionId)
    }
}
