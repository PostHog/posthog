/**
 * Session event bus. Production wires to Redis pub/sub; tests use the
 * in-memory impl below. Carries assistant token streaming + tool-call deltas
 * back to listening clients (chat /listen, MCP transport).
 */

export interface SessionEvent {
    session_id: string
    kind: 'assistant_text' | 'tool_call' | 'tool_result' | 'completed' | 'waiting' | 'error'
    data: Record<string, unknown>
    ts: string
}

export interface SessionEventBus {
    publish(event: SessionEvent): Promise<void>
    subscribe(sessionId: string, fn: (e: SessionEvent) => void): () => void
}

export class MemorySessionEventBus implements SessionEventBus {
    private readonly subs = new Map<string, Set<(e: SessionEvent) => void>>()

    async publish(event: SessionEvent): Promise<void> {
        const set = this.subs.get(event.session_id)
        if (!set) {
            return
        }
        for (const fn of set) {
            try {
                fn(event)
            } catch {
                // ignore subscriber errors so one bad listener doesn't break others
            }
        }
    }

    subscribe(sessionId: string, fn: (e: SessionEvent) => void): () => void {
        let set = this.subs.get(sessionId)
        if (!set) {
            set = new Set()
            this.subs.set(sessionId, set)
        }
        set.add(fn)
        return () => {
            set!.delete(fn)
            if (set!.size === 0) {
                this.subs.delete(sessionId)
            }
        }
    }
}
