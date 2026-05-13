import { LLMTrace, LLMTraceEvent } from '~/queries/schema/schema-general'

import { messageSignature } from './messageSignature'
import { CompatMessage } from './types'
import { formatAiErrorForDisplay, normalizeMessage, normalizeMessages } from './utils'

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

/**
 * Pulls tool names out of an `$ai_output_choices` payload. Covers two shapes:
 * - OpenAI: `[{tool_calls: [{function: {name}}]}]` (and Chat Completions
 *   `{choices: [...]}`, LiteLLM `{message: {tool_calls: [...]}}`).
 * - Anthropic: typed content parts `[{type: 'tool_use', name, input}]`.
 *
 * Unrecognised shapes are skipped silently — we surface what we can and degrade
 * gracefully on the rest.
 */
function extractToolNamesFromOutput(rawOutput: unknown): string[] {
    const names: string[] = []
    const messages: unknown[] = Array.isArray(rawOutput)
        ? rawOutput
        : typeof rawOutput === 'object' &&
            rawOutput !== null &&
            'choices' in rawOutput &&
            Array.isArray((rawOutput as { choices: unknown[] }).choices)
          ? (rawOutput as { choices: unknown[] }).choices
          : []
    for (const raw of messages) {
        if (!raw || typeof raw !== 'object') {
            continue
        }
        const msg = 'message' in raw ? (raw as { message: unknown }).message : raw
        if (!msg || typeof msg !== 'object') {
            continue
        }
        const toolCalls = (msg as { tool_calls?: unknown }).tool_calls
        if (Array.isArray(toolCalls)) {
            for (const call of toolCalls) {
                const name = (call as { function?: { name?: unknown } })?.function?.name
                if (typeof name === 'string' && name) {
                    names.push(name)
                }
            }
        }
        const content = (msg as { content?: unknown }).content
        if (Array.isArray(content)) {
            for (const part of content) {
                if (part && typeof part === 'object' && (part as { type?: unknown }).type === 'tool_use') {
                    const name = (part as { name?: unknown }).name
                    if (typeof name === 'string' && name) {
                        names.push(name)
                    }
                }
            }
        }
    }
    return names
}

/**
 * Distinct tool names in chronological first-appearance order. Pulled from
 * `$ai_span_name` on instrumented `$ai_span` events plus `tool_calls` /
 * `tool_use` parts in `$ai_generation` outputs.
 */
function collectToolsCalled(events: LLMTraceEvent[]): string[] {
    // Sort chronologically so "first-appearance order" is deterministic regardless
    // of whatever order ClickHouse returned the events in.
    const sorted = [...events].sort((a, b) => new Date(a.createdAt).getTime() - new Date(b.createdAt).getTime())
    const seen = new Set<string>()
    const ordered: string[] = []
    const add = (name: string): void => {
        if (!seen.has(name)) {
            seen.add(name)
            ordered.push(name)
        }
    }
    for (const event of sorted) {
        if (event.event === '$ai_span') {
            const spanName = event.properties.$ai_span_name
            if (typeof spanName === 'string' && spanName) {
                add(spanName)
            }
        } else if (event.event === '$ai_generation') {
            for (const name of extractToolNamesFromOutput(event.properties.$ai_output_choices)) {
                add(name)
            }
        }
    }
    return ordered
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
        // PostHog SDKs serialize booleans as strings, so `$ai_is_error: 'false'` is
        // a truthy non-empty string. Explicit non-error takes priority over
        // `$ai_error` presence — some SDKs record a partial error object during a
        // retry that ultimately resolves successfully, then mark the final event as
        // non-error.
        const isErrorFlag = event.properties.$ai_is_error
        if (isErrorFlag === false || isErrorFlag === 'false') {
            continue
        }
        const isError = isErrorFlag === true || isErrorFlag === 'true' || event.properties.$ai_error
        if (!isError) {
            continue
        }
        const label =
            (event.properties.$ai_span_name as string | undefined) ||
            (event.properties.$ai_model as string | undefined) ||
            event.event
        const rawError = event.properties.$ai_error
        const message =
            typeof rawError === 'object' &&
            rawError !== null &&
            'message' in rawError &&
            typeof (rawError as { message: unknown }).message === 'string'
                ? (rawError as { message: string }).message
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
        const tools = collectToolsCalled(fullTrace.events ?? [])
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
        const rawInput = properties.$ai_input ?? properties.$ai_input_state
        const rawOutput = properties.$ai_output_choices ?? properties.$ai_output_state ?? properties.$ai_output
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
