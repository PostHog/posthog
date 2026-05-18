import { SessionRegistry } from '@repo/ass-server/sse'

import { SessionBus, SessionEvent, SessionLogStore, logger } from '@posthog/agent-core'

/**
 * Bridges ass-server's in-process event sink onto PostHog's SessionBus.
 *
 * `runSession` calls `registry.emit(id, event, data)` for SDK assistant messages,
 * tool-use summaries, results, and errors. We subclass SessionRegistry so we can
 * intercept those calls and translate the ones that map cleanly onto the
 * `SessionEvent` discriminated union the bus expects.
 *
 * Events without a clean mapping (e.g. `session_init`, `awaiting_input`, ad-hoc
 * `emit_event` payloads) are dropped for v1 — the listener API only knows about
 * the canonical set today. The bridge also tracks the final SDK result + any
 * thrown error so the executor can decide between `completed` and `failed`.
 *
 * The worker is responsible for `turn_started` / `turn_completed` / terminal
 * `session_completed` | `session_failed` envelopes — this bridge never emits
 * those, to keep responsibilities sharp.
 */
export interface CapturedResult {
    text?: string
    usage?: unknown
    total_cost_usd?: number
}

export class BusBridgingRegistry extends SessionRegistry {
    lastError: string | null = null
    lastResult: CapturedResult | null = null

    constructor(
        private readonly bus: SessionBus,
        private readonly busSessionId: string,
        /** Optional log buffer — when present, every mapped SessionEvent is
         *  also persisted for the UI's live tail / replay. */
        private readonly logStore?: SessionLogStore
    ) {
        super()
    }

    override emit(_id: string, event: string, data: unknown): void {
        const at = new Date().toISOString()
        const mapped = this.mapEvent(event, data, at)
        if (mapped) {
            void this.bus.publishEvent(this.busSessionId, mapped).catch((err) => {
                logger.error('runner bridge publish failed', {
                    sessionId: this.busSessionId,
                    event,
                    error: String(err),
                })
            })
            // Persist for the UI's session-log endpoint. Best-effort —
            // failure here shouldn't break the run.
            if (this.logStore) {
                void this.logStore.append(this.busSessionId, { kind: 'event', ...mapped }).catch((err) => {
                    logger.warn('runner bridge log append failed', {
                        sessionId: this.busSessionId,
                        event,
                        error: String(err),
                    })
                })
            }
        }
        // Track terminal signals regardless of whether we forwarded them.
        if (event === 'error') {
            const d = data as { message?: string }
            this.lastError = d?.message ?? 'unknown error'
        } else if (event === 'result') {
            this.lastResult = data as CapturedResult
        }
    }

    override finalize(_id: string): void {
        // No-op: the worker emits the terminal `session_completed`/`session_failed`
        // after `runSession.done` resolves. Emitting from here would race with that
        // and confuse SSE listeners.
    }

    private mapEvent(event: string, data: unknown, at: string): SessionEvent | null {
        switch (event) {
            case 'assistant_message': {
                const d = data as { content: unknown }
                return {
                    type: 'message',
                    role: 'assistant',
                    at,
                    content: typeof d?.content === 'string' ? d.content : JSON.stringify(d?.content ?? ''),
                }
            }
            case 'tool_call': {
                const d = data as { tool?: string; summary?: unknown }
                return {
                    type: 'tool_call',
                    at,
                    tool: d?.tool ?? 'unknown',
                    args: d?.summary,
                }
            }
            default:
                return null
        }
    }
}
