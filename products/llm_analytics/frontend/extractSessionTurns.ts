import { LLMTrace, LLMTraceEvent } from '~/queries/schema/schema-general'

import { messageSignature } from './messageSignature'
import { CompatMessage } from './types'
import {
    eventLabel,
    formatAiErrorForDisplay,
    getToolNamesCalled,
    normalizeMessage,
    normalizeMessages,
    readAiInput,
    readAiOutput,
} from './utils'

// Heuristic mirrors the LLMA skill script `print_summary.py` at
// `products/llm_analytics/skills/exploring-llm-traces/scripts/` — keep in sync.

/**
 * Pick the event that represents the user-visible turn for a trace.
 *
 * Current heuristic: the latest `$ai_generation` by `createdAt` — an
 * implementation detail callers should treat as opaque. A future opt-in
 * `$ai_user_visible: true` convention would change how this picks. Wrong
 * for traces where the last generation is a logging/cleanup call; the
 * "Show steps" affordance is the user's fallback.
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
 * Maps each normalized message back to its index in the raw `$ai_input`.
 * Many-to-one: `normalizeMessage` may expand one raw entry into multiple
 * messages. A leading `-1` marks the synthetic "available tools" message.
 *
 * Used by `ConversationMessagesDisplay` to map per-message sentiment to the
 * right rendered bubble after dedup. Also used by the Trace page renderer.
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

export interface SessionTurnError {
    /** Human-readable label for *what* failed — `$ai_span_name`, `$ai_model`, or the raw event type as a last resort. */
    label: string
    /** Extracted error message. For `$ai_error` objects we surface `.message` directly; everything else is JSON-stringified. */
    message: string
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
    /** The event sourced by `pickUserVisibleTurn` — used for model, error, latency, and the id passed to renderers. */
    userVisibleTurn?: LLMTraceEvent
    /**
     * Distinct tool names called in this turn, in first-appearance order. Pulled
     * from both `$ai_span_name` on instrumented `$ai_span` events and from
     * `tool_calls` / `tool_use` parts in generation outputs.
     */
    tools: string[]
    /**
     * Distinct errors in the trace, deduped by `label + message` and ordered by
     * first chronological occurrence. Retries of the same failure collapse to a
     * single entry; truly distinct failures all appear. `trace.errorCount` still
     * reflects total error events (including retries); `errors.length` is the
     * count of UNIQUE kinds.
     */
    errors: SessionTurnError[]
}

function getToolNamesCalledUnique(events: LLMTraceEvent[]): string[] {
    // `Set` insertion order preserves first-appearance
    return Array.from(new Set(getToolNamesCalled(events)))
}

/**
 * Distinct errors keyed by `label + message`, in chronological first-appearance
 * order. Retries of the same failure collapse to one entry. The chip already
 * shows the raw event count (including retries); listing *distinct kinds* of
 * failures inline reads more usefully than listing every retry.
 */
function collectDistinctErrors(events: LLMTraceEvent[]): SessionTurnError[] {
    const sorted = [...events].sort((a, b) => new Date(a.createdAt).getTime() - new Date(b.createdAt).getTime())
    const seen = new Set<string>()
    const ordered: SessionTurnError[] = []
    for (const event of sorted) {
        // A populated `$ai_error` payload is the authoritative signal — if it's
        // there, treat the event as an error regardless of `$ai_is_error`.
        // (Note that PostHog SDKs serialize booleans as strings)
        const hasErrorPayload = !!event.properties.$ai_error
        const isErrorFlag = event.properties.$ai_is_error
        const isError = hasErrorPayload || isErrorFlag === true || isErrorFlag === 'true'
        if (!isError) {
            continue
        }
        const label = eventLabel(event)
        const rawError = event.properties.$ai_error
        const message =
            typeof rawError === 'object' &&
            rawError !== null &&
            'message' in rawError &&
            typeof rawError.message === 'string'
                ? rawError.message
                : formatAiErrorForDisplay(rawError)
        const key = `${label}::${message}`
        if (!seen.has(key)) {
            seen.add(key)
            ordered.push({ label, message })
        }
    }
    return ordered
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
                tools: [],
                errors: [],
            }
        }
        const tools = getToolNamesCalledUnique(fullTrace.events ?? [])
        const errors = collectDistinctErrors(fullTrace.events ?? [])
        const userVisibleTurn = pickUserVisibleTurn(fullTrace)
        if (!userVisibleTurn) {
            return {
                trace,
                isLoaded: true,
                newInputs: [],
                outputs: [],
                tools,
                errors,
            }
        }
        const { properties } = userVisibleTurn
        const rawInput = readAiInput(properties)
        const rawOutput = readAiOutput(properties)
        const aiTools = properties.$ai_tools

        const inputMessages = normalizeMessages(rawInput, 'user', aiTools)
        const outputMessages = normalizeMessages(rawOutput, 'assistant')

        const newInputs: CompatMessage[] = []
        const msgCountThisTurn = new Map<string, number>()
        for (const message of inputMessages) {
            const sig = messageSignature(message)
            const turnCount = (msgCountThisTurn.get(sig) ?? 0) + 1
            msgCountThisTurn.set(sig, turnCount)
            const shownCount = msgCountShown.get(sig) ?? 0
            if (turnCount > shownCount) {
                newInputs.push(message)
                msgCountShown.set(sig, turnCount)
            }
        }
        for (const message of outputMessages) {
            const sig = messageSignature(message)
            msgCountShown.set(sig, (msgCountShown.get(sig) ?? 0) + 1)
        }

        return {
            trace,
            isLoaded: true,
            newInputs,
            outputs: outputMessages,
            userVisibleTurn,
            tools,
            errors,
        }
    })
}
