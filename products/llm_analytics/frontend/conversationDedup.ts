import { LLMTrace, LLMTraceEvent } from '~/queries/schema/schema-general'

import { CompatMessage } from './types'
import { normalizeMessage, normalizeMessages } from './utils'

// ─────────────────────────────────────────────────────────────────────────────
// Heuristics in this module mirror the LLMA agent skill scripts at
// `products/llm_analytics/skills/exploring-llm-traces/scripts/`:
//
//   * `extract_conversation.py` — iterates `$ai_generation` events sorted by
//     createdAt and reads role/content/tool_calls off `$ai_input` (the running
//     message history) plus `$ai_output_choices` (the model's reply). That's
//     the field set `messageSignature` keys on and the input shape this module
//     reads.
//
//   * `print_summary.py` — picks `generations[-1]` (the last `$ai_generation`
//     event in the trace) as "the final LLM output". That's the convention
//     `pickUserVisibleTurn` implements (named for the intent, not the mechanism).
//
// Keeping the UI and the skill aligned means agents and humans see the same
// conversation for a given trace. The Python is the existing reference; if we
// invented a different heuristic here, divergence between the two surfaces
// would be silent and confusing.
//
// Known limitation, same as the skill: for noisy LangGraph-style traces where
// the user-visible reply is structurally identified rather than positional,
// the "last generation" heuristic can pick the wrong event. The intended
// escape hatch is an opt-in `$ai_user_visible: true` convention on the SDK
// side; until that lands, the "Show reasoning" affordance is the user's fallback.
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Provider-specific transport metadata that lives on typed content parts but
 * does NOT change what the user sees. Stripped before signing so that the
 * same user-visible message dedups across turns even if the caller changes
 * its cache hint, the SDK adds a verification signature, or routing metadata
 * differs between echoes.
 *
 *   - `cache_control` — Anthropic ephemeral-cache directives on text parts.
 *     Callers commonly add/remove these mid-session as the prefix stabilises.
 *   - `signature` — Anthropic cryptographic signature on `thinking` parts.
 *     Not user-visible; can vary between echoes of the same reasoning step.
 *   - `caller` — routing metadata observed on `tool_use` parts in production.
 *     Not user-visible.
 *
 * The replacer fires recursively for every key during serialisation, so these
 * fields are dropped at any nesting level.
 */
const TRANSPORT_METADATA_KEYS = new Set(['cache_control', 'signature', 'caller'])

function isPlainTextPart(part: unknown): boolean {
    return (
        typeof part === 'object' &&
        part !== null &&
        (part as Record<string, unknown>).type === 'text' &&
        typeof (part as Record<string, unknown>).text === 'string'
    )
}

function normalizeSignatureField(key: string, value: unknown): unknown {
    if (TRANSPORT_METADATA_KEYS.has(key)) {
        return undefined
    }
    // Converge text-only typed-parts arrays with their flat-string equivalent.
    // SDKs round-trip the same assistant reply between
    // `{role: 'assistant', content: 'Hello'}` (OpenAI flat-string output) and
    // `{role: 'assistant', content: [{type: 'text', text: 'Hello'}]}` (the app
    // stores history as typed parts and feeds it back as the next call's
    // input). Without this convergence the signature for the output differs
    // from the signature for the next turn's input copy of the same message,
    // and the assistant message re-renders. Only flatten when every part is a
    // plain text part — mixed content (text + tool_use, etc.) keeps its
    // typed-parts shape because it has no flat-string equivalent.
    if (key === 'content' && Array.isArray(value) && value.length > 0 && value.every(isPlainTextPart)) {
        return value.map((part) => (part as { text: string }).text).join('')
    }
    return value
}

/**
 * Stable string hash for a normalized message, used to detect when later turns
 * are re-sending an earlier turn's message in their `$ai_input` history.
 *
 * Two messages are considered "the same turn" iff their role, content,
 * tool_calls, tool_call_id, and (synthetic) tools list all match exactly,
 * **ignoring transport metadata** (see `TRANSPORT_METADATA_KEYS`) and
 * **after converging text-only typed-parts arrays with their flat-string
 * equivalent** (see `normalizeSignatureField`). The field set mirrors what
 * `extract_conversation.py` reads when rendering each turn — role/content/
 * tool_calls — plus tool_call_id (for distinguishing tool responses that
 * share content but answer different calls) and tools (for the synthetic
 * "available tools" pseudo-message `normalizeMessages` prepends).
 *
 * Reused on the Session detail view (cross-trace transcript dedup) and
 * intended to be picked up by any future agent-mode view that needs
 * "have we shown this already?" semantics.
 */
export function messageSignature(message: CompatMessage): string {
    // JSON.stringify preserves order
    return JSON.stringify(
        {
            role: message.role ?? '',
            content: message.content ?? '',
            tool_calls: message.tool_calls ?? null,
            tool_call_id: message.tool_call_id ?? '',
            tools: (message as { tools?: unknown }).tools ?? null,
        },
        // Call normalizeSignatureField for each field above:
        normalizeSignatureField
    )
}

/**
 * Pick the event in a trace that represents the user-visible conversational
 * turn — the thing we want to render as "what the model said" for this trace.
 *
 * The current heuristic is the latest `$ai_generation` event by `createdAt`,
 * matching the LLMA agent skill (`print_summary.py` → `generations[-1]`). That
 * mechanism is an implementation detail of this function: callers should treat
 * the return value as "the turn", not "the last generation". A future
 * `$ai_user_visible: true` convention or a non-positional selector for
 * LangGraph-style runs would change *how* this function picks but not what it
 * promises. Wrong for cases where the final generation is e.g. a
 * logging/cleanup call; the "Show reasoning" affordance is the user's
 * fallback.
 */
export function pickUserVisibleTurn(trace: LLMTrace | undefined): LLMTraceEvent | undefined {
    if (!trace?.events?.length) {
        return undefined
    }
    let latest: LLMTraceEvent | undefined
    let latestTs = -Infinity
    for (const event of trace.events) {
        if (event.event !== '$ai_generation') {
            continue
        }
        const ts = new Date(event.createdAt).getTime()
        if (ts > latestTs) {
            latest = event
            latestTs = ts
        }
    }
    return latest
}

/**
 * Maps each normalized message back to its index in the raw `$ai_input` array.
 * `normalizeMessage` may expand one raw entry into multiple `CompatMessage`s
 * (e.g. typed content parts split into text + tool_call bubbles), so this is
 * many-to-one. A leading `-1` is emitted when a synthetic "available tools"
 * message has been prepended.
 *
 * Why this matters: `ConversationMessagesDisplay` uses these indices to map
 * per-message sentiment back to the right rendered bubble (see its
 * `getMessageSentiment` path). After dedup, the surviving messages would lose
 * that mapping unless we tracked their original positions — which is what this
 * function does. Also called by `ConversationDisplay` (the per-event renderer
 * on the Trace page) so both surfaces share one implementation.
 */
export function buildInputSourceIndices(rawInput: unknown, tools: unknown): number[] {
    const indices: number[] = []
    if (tools) {
        indices.push(-1)
    }
    if (Array.isArray(rawInput)) {
        for (let i = 0; i < rawInput.length; i++) {
            const expanded = normalizeMessage(rawInput[i], 'user')
            for (let j = 0; j < expanded.length; j++) {
                indices.push(i)
            }
        }
    }
    return indices
}

export interface SessionTurn {
    /** The trace this turn corresponds to. */
    trace: LLMTrace
    /** True if `fullTraces[trace.id]` was available and we computed messages. */
    isLoaded: boolean
    /** Input messages new to this turn (already-seen messages from prior turns hidden). */
    newInputs: CompatMessage[]
    /** Output messages from this turn's last generation. */
    outputs: CompatMessage[]
    /** Maps each `newInputs[i]` back to its source index in the raw `$ai_input` array. */
    newInputSourceIndices: number[]
    /**
     * The event in the trace that represents the user-visible turn — the
     * source of properties (model, error, latency, ...) and the id passed
     * to `ConversationMessagesDisplay`. Currently this is the last
     * `$ai_generation`, but consumers should treat it as opaque; see
     * `pickUserVisibleTurn` for the (implementation-detail) selection rule.
     */
    userVisibleTurn?: LLMTraceEvent
}

/**
 * Walk traces in order and hide inputs already shown in an earlier turn.
 * Without this, turn N would re-render turns 1..N-1 because each `$ai_input`
 * carries the full running history.
 *
 * Count-based, not set-based: a message at its Nth occurrence in a turn's
 * input renders iff fewer than N copies have been shown so far. Preserves
 * legitimate repeats within a turn.
 */
export function extractSessionTurns(traces: LLMTrace[], fullTraces: Record<string, LLMTrace>): SessionTurn[] {
    const msgCountShown = new Map<string, number>()
    return traces.map((trace) => {
        const fullTrace = fullTraces[trace.id]
        if (!fullTrace) {
            return {
                trace,
                isLoaded: false,
                newInputs: [],
                outputs: [],
                newInputSourceIndices: [],
            }
        }
        const userVisibleTurn = pickUserVisibleTurn(fullTrace)
        if (!userVisibleTurn) {
            return {
                trace,
                isLoaded: true,
                newInputs: [],
                outputs: [],
                newInputSourceIndices: [],
            }
        }
        const { properties } = userVisibleTurn
        const rawInput = properties.$ai_input ?? properties.$ai_input_state
        const rawOutput = properties.$ai_output_choices ?? properties.$ai_output_state ?? properties.$ai_output
        const tools = properties.$ai_tools

        const inputMessages = normalizeMessages(rawInput, 'user', tools)
        const outputMessages = normalizeMessages(rawOutput, 'assistant')
        const sourceIndices = buildInputSourceIndices(rawInput, tools)

        const newInputs: CompatMessage[] = []
        const newInputSourceIndices: number[] = []
        const msgCountThisTurn = new Map<string, number>()
        inputMessages.forEach((message, i) => {
            const sig = messageSignature(message)
            const turnCount = (msgCountThisTurn.get(sig) ?? 0) + 1
            msgCountThisTurn.set(sig, turnCount)
            const shownCount = msgCountShown.get(sig) ?? 0
            if (turnCount > shownCount) {
                newInputs.push(message)
                newInputSourceIndices.push(sourceIndices[i] ?? i)
                msgCountShown.set(sig, turnCount)
            }
        })
        for (const message of outputMessages) {
            const sig = messageSignature(message)
            msgCountShown.set(sig, (msgCountShown.get(sig) ?? 0) + 1)
        }

        return {
            trace,
            isLoaded: true,
            newInputs,
            outputs: outputMessages,
            newInputSourceIndices,
            userVisibleTurn,
        }
    })
}
