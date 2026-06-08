/**
 * Reduces agent-ingress SSE events into the `ChatSession` shape the
 * `<AgentChat />` dock renders.
 *
 * Pure function on (session, event) → session. No React, no async.
 * The hook (`useRealRunner`) is responsible for calling this on each
 * event delivery.
 *
 * Event catalogue (from `services/agent-ingress/src/triggers/chat.ts`
 * and `services/agent-runner/src/loop/bus.ts`):
 *   session_started          → `{ team_id, agent, rev }`
 *   turn_started             → `{ turn }`
 *   assistant_text_delta     → `{ turn, text }`        grow streaming text part
 *   assistant_thinking_delta → `{ turn, thinking }`    grow thinking part
 *   tool_call_start          → `{ turn, id, name }`    push pending tool_call
 *   tool_call_args_delta     → `{ turn, id, argsDelta }` accumulate args text
 *   assistant_text           → `{ text }`              turn-end snapshot (ignored — deltas already filled it)
 *   tool_call                → `{ id, name, args }`    finalize tool_call args
 *   tool_result              → `{ id, tool, outcome, output }` set result
 *   completed                → `{ turns, summary? }`   state=completed
 *   waiting                  → `{ turns, prompt }`     state=awaiting_approval
 *   failed                   → `{ reason, turns }`     state=failed
 */

import type { AssistantTurn, AssistantTurnPart, ChatSession, Turn, UserTurn } from '@posthog/agent-chat'

import type { SessionEvent } from './agentIngressClient'

export function applyEvent(session: ChatSession, event: SessionEvent): ChatSession {
    switch (event.kind) {
        case 'session_started':
            return { ...session, state: 'streaming' }

        case 'user_message': {
            // Server-confirmed user message — emitted when the runner drains
            // an entry from pending_inputs. Reconciles the optimistic local
            // bubble (added in useRealRunner.send) with server-authoritative
            // conversation order. Search BACKWARDS across the whole turn
            // list: pi-agent-core fires turn_start before its
            // getSteeringMessages hook, so by the time user_message arrives
            // an assistant turn may already have been appended AFTER the
            // matching user turn. A post-last-assistant search would miss
            // it and double-render the bubble.
            const text = asString(event.data.text)
            if (!text) {
                return session
            }
            let matchIndex = -1
            for (let i = session.turns.length - 1; i >= 0; i--) {
                const t = session.turns[i]
                if (t.kind === 'user' && t.text === text) {
                    matchIndex = i
                    break
                }
            }
            if (matchIndex !== -1) {
                const existing = session.turns[matchIndex] as UserTurn
                if (existing.pending !== true) {
                    // turn_started already cleared the pending flag — the
                    // bubble is already confirmed in the transcript.
                    return session
                }
                const turns = session.turns.slice()
                turns[matchIndex] = { ...existing, pending: false }
                return { ...session, turns }
            }
            // No matching optimistic turn — append. Happens for messages
            // injected by another client on the same session, or when the
            // optimistic append was missed.
            const confirmed: UserTurn = {
                kind: 'user',
                id: `user-${asString(event.data.timestamp) || event.ts}`,
                timestamp: event.ts,
                text,
            }
            return { ...session, turns: [...session.turns, confirmed] }
        }

        case 'turn_started': {
            const turnId = `assistant-${event.data.turn ?? Date.now()}`
            if (session.turns.some((t) => t.id === turnId)) {
                return session
            }
            const assistantTurn: AssistantTurn = {
                kind: 'assistant',
                id: turnId,
                timestamp: event.ts,
                streaming: true,
                parts: [],
            }
            // A new turn means the runner has just drained `pending_inputs`
            // — any user turn we still had marked `pending` is now part of
            // the conversation the agent is responding to.
            const turns = session.turns.map<Turn>((t) =>
                t.kind === 'user' && t.pending ? { ...t, pending: false } : t
            )
            return { ...session, state: 'streaming', turns: [...turns, assistantTurn] }
        }

        case 'assistant_text_delta':
            return updateActiveAssistant(session, (parts) => growTextPart(parts, asString(event.data.text)))

        case 'assistant_thinking_delta':
            return updateActiveAssistant(session, (parts) => growThinkingPart(parts, asString(event.data.thinking)))

        case 'tool_call_start': {
            const id = asString(event.data.id)
            const name = asString(event.data.name)
            return updateActiveAssistant(session, (parts) => {
                if (parts.some((p) => p.kind === 'tool_call' && p.callId === id)) {
                    return parts
                }
                return [...parts, { kind: 'tool_call', toolId: name, callId: id, fulfillment: 'server', args: {} }]
            })
        }

        case 'tool_call_args_delta': {
            const id = asString(event.data.id)
            const argsDelta = event.data.argsDelta
            return updateActiveAssistant(session, (parts) =>
                parts.map((p) => {
                    if (p.kind !== 'tool_call' || p.callId !== id) {
                        return p
                    }
                    return { ...p, args: mergeArgsDelta(p.args, argsDelta) }
                })
            )
        }

        case 'tool_call': {
            // Turn-end snapshot — replace any partial args with the
            // canonical version.
            const id = asString(event.data.id)
            const name = asString(event.data.name)
            const args = (event.data.args as Record<string, unknown> | undefined) ?? {}
            return updateActiveAssistant(session, (parts) => {
                if (!parts.some((p) => p.kind === 'tool_call' && p.callId === id)) {
                    return [...parts, { kind: 'tool_call', toolId: name, callId: id, fulfillment: 'server', args }]
                }
                return parts.map((p) => (p.kind === 'tool_call' && p.callId === id ? { ...p, toolId: name, args } : p))
            })
        }

        case 'tool_result': {
            const id = asString(event.data.id)
            const ok = event.data.ok === true
            const output = event.data.output
            const errorText = typeof event.data.error === 'string' ? event.data.error : ''
            // Interactive client tools return a synthetic `{queued:true, interactive:true}`
            // envelope from `execute` so the loop unwinds — the call is still
            // pending the user's form submission. Leave `part.result` unset so
            // PartRenderer keeps the inline slot mounted, but flip the
            // fulfillment to 'client' so the slot logic actually runs.
            if (ok && isInteractiveQueuedEnvelope(output)) {
                return updateActiveAssistant(session, (parts) =>
                    parts.map((p) => (p.kind === 'tool_call' && p.callId === id ? { ...p, fulfillment: 'client' } : p))
                )
            }
            return updateActiveAssistant(session, (parts) =>
                parts.map((p) => {
                    if (p.kind !== 'tool_call' || p.callId !== id) {
                        return p
                    }
                    const result = ok
                        ? ({ ok: true, body: output } as const)
                        : ({ ok: false, error: errorText || 'tool_failed' } as const)
                    return { ...p, result }
                })
            )
        }

        case 'client_tool_result': {
            // Wake fired by the runner's resume scanner after `/send` delivered
            // the user's form outcome. Locate the matching tool_call across
            // every assistant turn (the queued envelope may have completed
            // turns ago) and finalise its result.
            const id = asString(event.data.call_id)
            const hasError = typeof event.data.error === 'string'
            const result = hasError
                ? ({ ok: false, error: (event.data.error as string) || 'client_tool_failed' } as const)
                : ({ ok: true, body: event.data.result ?? null } as const)
            return updateTurnsAcrossAssistants(session, (parts) =>
                parts.map((p) =>
                    p.kind === 'tool_call' && p.callId === id ? { ...p, fulfillment: 'client', result } : p
                )
            )
        }

        case 'assistant_text':
            // Turn-end snapshot of the full text; deltas already wrote
            // it. Also marks the turn as no-longer-streaming.
            return finalizeActiveTurn(session)

        case 'completed':
            return { ...finalizeActiveTurn(session), state: 'completed' }

        case 'waiting':
            return { ...session, state: 'awaiting_approval' }

        case 'failed': {
            // Surface a generic, non-leaky message to the end user. The
            // raw `reason` from the runner can carry implementation
            // detail (transport type, internal URLs, stack-shaped strings,
            // upstream provider error bodies) that doesn't belong in
            // someone-else's-agent chat surfaces. The raw reason is
            // still on the bus event for anything downstream that
            // needs it, and the worker writes it to log_entries for
            // the agent owner to read via the session-detail page —
            // the chat just renders a session-id reference the user
            // can share with the agent owner. Also clear `pending` on
            // any optimistic user turn — the message reached the
            // server (the failure happened after enqueue), so it
            // shouldn't stay "Sending…" forever.
            const errorMessage = `This session failed. Reference: ${session.id} — share with the agent owner to investigate.`
            const finalized = finalizeActiveTurn(session)
            const turns = finalized.turns.map<Turn>((t) =>
                t.kind === 'user' && t.pending ? { ...t, pending: false } : t
            )
            return { ...finalized, turns, state: 'failed', error: errorMessage }
        }

        default:
            return session
    }
}

function asString(v: unknown): string {
    return typeof v === 'string' ? v : ''
}

/**
 * Tool call args arrive as deltas — sometimes they're string fragments
 * to be concatenated into JSON, sometimes they're already-parsed
 * partial objects. We accept both, accumulating into a shape the UI
 * can render. v0.1 — the runner emits raw stream chunks; for now we
 * just preserve whichever shape arrives and let the JsonView render it.
 */
function mergeArgsDelta(current: Record<string, unknown>, delta: unknown): Record<string, unknown> {
    if (delta == null) {
        return current
    }
    if (typeof delta === 'string') {
        const previous = (current.__rawStream as string | undefined) ?? ''
        return { ...current, __rawStream: previous + delta }
    }
    if (typeof delta === 'object') {
        return { ...current, ...(delta as Record<string, unknown>) }
    }
    return current
}

function updateTurnsAcrossAssistants(
    session: ChatSession,
    transform: (parts: AssistantTurnPart[]) => AssistantTurnPart[]
): ChatSession {
    return {
        ...session,
        turns: session.turns.map<Turn>((t) => (t.kind === 'assistant' ? { ...t, parts: transform(t.parts) } : t)),
    }
}

function isInteractiveQueuedEnvelope(output: unknown): boolean {
    if (!output || typeof output !== 'object') {
        return false
    }
    const o = output as Record<string, unknown>
    return o.queued === true && o.interactive === true && typeof o.call_id === 'string'
}

function updateActiveAssistant(
    session: ChatSession,
    transform: (parts: AssistantTurnPart[]) => AssistantTurnPart[]
): ChatSession {
    const lastAssistantIndex = findLastAssistantIndex(session.turns)
    if (lastAssistantIndex === -1) {
        // No assistant turn yet — synthesize one so deltas have somewhere to land.
        const assistantTurn: AssistantTurn = {
            kind: 'assistant',
            id: `assistant-${Date.now()}`,
            timestamp: new Date().toISOString(),
            streaming: true,
            parts: transform([]),
        }
        return { ...session, state: 'streaming', turns: [...session.turns, assistantTurn] }
    }
    return {
        ...session,
        state: 'streaming',
        turns: session.turns.map<Turn>((t, i) =>
            i === lastAssistantIndex && t.kind === 'assistant' ? { ...t, parts: transform(t.parts) } : t
        ),
    }
}

function growTextPart(parts: AssistantTurnPart[], chunk: string): AssistantTurnPart[] {
    if (!chunk) {
        return parts
    }
    const last = parts.at(-1)
    if (last && last.kind === 'text') {
        return [...parts.slice(0, -1), { kind: 'text', text: last.text + chunk }]
    }
    return [...parts, { kind: 'text', text: chunk }]
}

function growThinkingPart(parts: AssistantTurnPart[], chunk: string): AssistantTurnPart[] {
    if (!chunk) {
        return parts
    }
    const last = parts.at(-1)
    if (last && last.kind === 'thinking') {
        return [...parts.slice(0, -1), { kind: 'thinking', text: last.text + chunk }]
    }
    return [...parts, { kind: 'thinking', text: chunk }]
}

function finalizeActiveTurn(session: ChatSession): ChatSession {
    const lastAssistantIndex = findLastAssistantIndex(session.turns)
    if (lastAssistantIndex === -1) {
        return session
    }
    return {
        ...session,
        state: 'idle',
        turns: session.turns.map<Turn>((t, i) =>
            i === lastAssistantIndex && t.kind === 'assistant' ? { ...t, streaming: false } : t
        ),
    }
}

function findLastAssistantIndex(turns: Turn[]): number {
    for (let i = turns.length - 1; i >= 0; i--) {
        if (turns[i].kind === 'assistant') {
            return i
        }
    }
    return -1
}
