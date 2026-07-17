/**
 * Bounds the size of an LLM trace result before it is serialized toward the MCP
 * client. `query-llm-trace` returns every event in a trace at every nesting
 * depth, and each event carries its full `properties` — including entire LLM
 * prompts, completions, and tool payloads. Left unbounded these responses have
 * reached tens of millions of tokens, which exhausts the calling agent's context
 * window. Compaction keeps the trace shape (all metadata, the event tree, small
 * values) intact while capping the two things that actually blow up: individual
 * long string values, and the total number of events.
 *
 * This is a client-boundary safeguard only — the underlying query and the
 * PostHog UI still have the complete, untruncated trace. Truncated values and
 * dropped events are flagged so the agent knows to open the trace in PostHog for
 * the full data.
 */

/** Longest single string value kept verbatim; longer values are truncated. */
export const PER_VALUE_CHAR_LIMIT = 10_000

/**
 * Hard cap on the serialized size of a single trace (~125K tokens at the
 * ~4-chars-per-token heuristic). Comfortably below any agent context window
 * while still large enough to inspect a real multi-step trace.
 */
export const MAX_TRACE_CHARS = 500_000

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function serializedLength(value: unknown): number {
    try {
        return JSON.stringify(value)?.length ?? 0
    } catch {
        return 0
    }
}

function truncateString(value: string): string {
    if (value.length <= PER_VALUE_CHAR_LIMIT) {
        return value
    }
    const dropped = value.length - PER_VALUE_CHAR_LIMIT
    return `${value.slice(0, PER_VALUE_CHAR_LIMIT)}… [truncated ${dropped} of ${value.length} chars — open the trace in PostHog for the full value]`
}

/** Recursively truncate every long string value, leaving structure untouched. */
function truncateLongStrings(value: unknown): unknown {
    if (typeof value === 'string') {
        return truncateString(value)
    }
    if (Array.isArray(value)) {
        return value.map(truncateLongStrings)
    }
    if (isRecord(value)) {
        const out: Record<string, unknown> = {}
        for (const [key, inner] of Object.entries(value)) {
            out[key] = truncateLongStrings(inner)
        }
        return out
    }
    return value
}

/**
 * Compact a single trace object: truncate long string values, then, if the trace
 * is still over budget, keep as many leading events as fit and flag the rest.
 * Events are ordered chronologically, so the earliest steps — usually the most
 * useful for reconstructing what happened — are the ones retained.
 */
export function compactTrace(trace: unknown): unknown {
    if (!isRecord(trace)) {
        return trace
    }
    const truncated = truncateLongStrings(trace) as Record<string, unknown>
    const events = truncated.events
    if (!Array.isArray(events) || serializedLength(truncated) <= MAX_TRACE_CHARS) {
        return truncated
    }

    // Greedily keep leading events until the running serialized size would exceed
    // the budget. Measuring each event once keeps this linear in event count.
    const base = { ...truncated, events: [] as unknown[] }
    let used = serializedLength(base)
    const kept: unknown[] = []
    for (const event of events) {
        const eventLength = serializedLength(event) + 1 // +1 for the array separator
        if (kept.length >= 1 && used + eventLength > MAX_TRACE_CHARS) {
            break
        }
        kept.push(event)
        used += eventLength
    }
    if (kept.length === events.length) {
        return truncated
    }
    return {
        ...truncated,
        events: kept,
        _truncated: {
            omittedEvents: events.length - kept.length,
            totalEvents: events.length,
            reason: 'Trace exceeded the response size limit; trailing events were omitted.',
            note: 'Open the trace in PostHog to inspect all events, or narrow the query to the events you need.',
        },
    }
}

/**
 * Compact the `results` array returned by a trace query. `query-llm-trace`
 * returns a single trace; the shape is an array either way, so each entry is
 * compacted independently.
 */
export function compactTraceResults(results: unknown): unknown {
    if (!Array.isArray(results)) {
        return results
    }
    return results.map(compactTrace)
}
