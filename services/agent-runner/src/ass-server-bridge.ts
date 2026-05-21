import { SessionRegistry } from '@repo/ass-server/sse'

import { SessionBus, SessionEvent, SessionLogger, logger } from '@posthog/agent-core'

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
        private readonly sessionLogger: SessionLogger
    ) {
        super()
    }

    override emit(_id: string, event: string, data: unknown): void {
        const at = new Date().toISOString()
        const mapped = this.mapEvents(event, data, at)
        for (const out of mapped) {
            void this.bus.publishEvent(this.busSessionId, out).catch((err) => {
                logger.error('runner bridge publish failed', {
                    sessionId: this.busSessionId,
                    event,
                    error: String(err),
                })
            })
            this.sessionLogger.appendEvent(out)
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

    /**
     * One ass-server event can become *zero or more* SessionBus events. Most
     * importantly, an `assistant_message` from the SDK arrives as an array of
     * content blocks (text + tool_use + thinking, mixed). We fan those out
     * into one `message`-per-text-block plus one `tool_call`-per-tool_use,
     * dropping signed thinking blocks (not for humans). Without the fan-out
     * the listener would see a JSON-stringified block array in `content`.
     */
    private mapEvents(event: string, data: unknown, at: string): SessionEvent[] {
        switch (event) {
            case 'assistant_message':
                return this.fanAssistantMessage(data, at)
            case 'tool_call': {
                const d = data as { tool?: string; summary?: unknown }
                return [
                    {
                        type: 'tool_call',
                        at,
                        tool: d?.tool ?? 'unknown',
                        args: d?.summary,
                    },
                ]
            }
            case 'message_delta': {
                // Streamed token chunk of the in-flight assistant reply. Forwarded
                // live to SSE listeners; the session-logger drops it (ephemeral —
                // never persisted). See pubsub/types `message_delta`.
                const d = data as { text?: unknown }
                if (typeof d?.text !== 'string') {
                    return []
                }
                return [{ type: 'message_delta', at, text: d.text }]
            }
            case 'status': {
                // `notify_user` meta tool — `{ text }` from session-runner.
                const d = data as { text?: unknown }
                if (typeof d?.text !== 'string') {
                    return []
                }
                return [{ type: 'status', at, text: d.text }]
            }
            case 'awaiting_input': {
                // `ask_for_input` meta tool — agent has suspended pending /send/:id.
                const d = data as { prompt?: unknown }
                const prompt = typeof d?.prompt === 'string' ? d.prompt : null
                return [{ type: 'awaiting_input', at, prompt }]
            }
            default:
                return []
        }
    }

    private fanAssistantMessage(data: unknown, at: string): SessionEvent[] {
        const d = data as { content?: unknown }
        let content: unknown = d?.content
        // Defensive: if an older upstream double-encoded the block array,
        // recover by parsing once.
        if (typeof content === 'string' && content.startsWith('[')) {
            try {
                content = JSON.parse(content)
            } catch {
                /* fall through to plain-string handling */
            }
        }
        if (Array.isArray(content)) {
            const out: SessionEvent[] = []
            for (const part of content) {
                if (!part || typeof part !== 'object') {
                    continue
                }
                const block = part as Record<string, unknown>
                if (block.type === 'text' && typeof block.text === 'string' && block.text.length > 0) {
                    out.push({ type: 'message', role: 'assistant', at, content: block.text })
                } else if (block.type === 'tool_use') {
                    out.push({
                        type: 'tool_call',
                        at,
                        tool: typeof block.name === 'string' ? block.name : 'unknown',
                        args: block.input,
                    })
                }
                // thinking / redacted_thinking: silently dropped
            }
            return out
        }
        if (typeof content === 'string' && content.length > 0) {
            return [{ type: 'message', role: 'assistant', at, content }]
        }
        return []
    }
}
