/**
 * Session event bus. Production wires to Redis pub/sub; tests use the
 * in-memory impl below. Carries lifecycle events from the runner to listening
 * clients (chat /listen, MCP transport, future telemetry sinks).
 */

export type SessionEventKind =
    | 'session_started'
    | 'turn_started'
    | 'assistant_text'
    | 'tool_call'
    | 'tool_result'
    | 'completed'
    | 'waiting'
    | 'failed'

export interface SessionEvent {
    session_id: string
    kind: SessionEventKind
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

/** A no-op bus — drop events on the floor. Useful for production runners
 *  that don't have a bus wired yet. */
export class NoopSessionEventBus implements SessionEventBus {
    async publish(_event: SessionEvent): Promise<void> {
        // intentionally empty
    }
    subscribe(_sessionId: string, _fn: (e: SessionEvent) => void): () => void {
        return () => undefined
    }
}
