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

import type { AssistantTurn, AssistantTurnPart, ChatSession, Turn } from '@posthog/agent-chat'

import type { SessionEvent } from './agentIngressClient'

export function applyEvent(session: ChatSession, event: SessionEvent): ChatSession {
    switch (event.kind) {
        case 'session_started':
            return { ...session, state: 'streaming' }

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
            const outcome = asString(event.data.outcome)
            const output = event.data.output
            return updateActiveAssistant(session, (parts) =>
                parts.map((p) => {
                    if (p.kind !== 'tool_call' || p.callId !== id) {
                        return p
                    }
                    const result =
                        outcome === 'ok' || outcome === 'success'
                            ? ({ ok: true, body: output } as const)
                            : ({ ok: false, error: String(output ?? outcome) } as const)
                    return { ...p, result }
                })
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

        case 'failed':
            return { ...finalizeActiveTurn(session), state: 'failed' }

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
