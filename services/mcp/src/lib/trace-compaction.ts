/**
 * Bounds the size of LLM trace results before they are serialized toward the MCP
 * client. `query-llm-trace` returns every event in a trace at every nesting
 * depth, and each event carries its full `properties` — entire LLM prompts,
 * completions, and tool payloads. Left unbounded these responses have reached
 * tens of millions of tokens, which exhausts the calling agent's context window.
 *
 * Compaction is a client-boundary safeguard only — the underlying query and the
 * PostHog UI still have the complete, untruncated trace. It walks the result
 * within a character budget, truncating long string values and dropping content
 * that doesn't fit, and stops traversing once the budget is spent so it never
 * materializes a full clone or a full serialization of a pathological trace.
 * Everything it shortens or drops is flagged so the agent knows to open the
 * trace in PostHog for the full data.
 */

/** Longest single string value kept verbatim; longer values are truncated. */
export const PER_VALUE_CHAR_LIMIT = 10_000

/**
 * Hard cap on the serialized size of a single trace, and on the combined size of
 * a trace-list response (~125K tokens at the ~4-chars-per-token heuristic).
 * Comfortably below any agent context window while still large enough to inspect
 * a real multi-step trace.
 */
export const MAX_TRACE_CHARS = 500_000

// Room reserved for events (and their truncation flag) when budgeting the
// non-event trace fields, so an oversized `inputState`/`outputState` can't starve
// the events out entirely.
const EVENTS_RESERVE = 50_000
// Room reserved for the `_truncated` metadata object.
const META_RESERVE = 500
// Below this remaining budget we stop adding more items rather than emit useless
// fragments. Also the floor budget handed to a forced-keep first event.
const MIN_ITEM_BUDGET = 256
// Smallest budget a trace may get in a multi-trace (list) response.
const MIN_TRACE_BUDGET = 2_000

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

/**
 * Assign a key without triggering the inherited `__proto__` setter. Trace
 * payloads are arbitrary parsed JSON and can legitimately carry an own
 * `__proto__` key (e.g. a tool payload being debugged); a plain `out[key] = v`
 * would set the clone's prototype instead of creating an own property and drop
 * the value from serialization.
 */
function assignKey(target: Record<string, unknown>, key: string, value: unknown): void {
    if (key === '__proto__') {
        Object.defineProperty(target, key, { value, enumerable: true, writable: true, configurable: true })
    } else {
        target[key] = value
    }
}

function truncateString(value: string, budget: number): string {
    const limit = Math.min(PER_VALUE_CHAR_LIMIT, Math.max(0, budget))
    if (value.length <= limit) {
        return value
    }
    const dropped = value.length - limit
    return `${value.slice(0, limit)}… [truncated ${dropped} of ${value.length} chars — open the trace in PostHog for the full value]`
}

interface Compacted {
    value: unknown
    /** Approximate serialized length of `value` (accurate for ASCII, the common case). */
    cost: number
}

/**
 * Compact a value so its serialized size stays within `budget` characters,
 * stopping as soon as the budget is spent. Long strings are truncated; array and
 * object members are kept until the budget runs out, then the remainder is
 * replaced with a short omission marker.
 */
function compactValue(value: unknown, budget: number): Compacted {
    if (value === null) {
        return { value: null, cost: 4 }
    }
    const type = typeof value
    if (type === 'number' || type === 'boolean') {
        return { value, cost: String(value).length }
    }
    if (type === 'string') {
        const out = truncateString(value as string, budget)
        return { value: out, cost: out.length + 2 }
    }
    if (Array.isArray(value)) {
        const out: unknown[] = []
        let cost = 2 // "[]"
        let i = 0
        for (; i < value.length; i++) {
            if (budget - cost < MIN_ITEM_BUDGET) {
                break
            }
            const child = compactValue(value[i], budget - cost - META_RESERVE)
            out.push(child.value)
            cost += child.cost + 1 // + comma
        }
        if (i < value.length) {
            const marker = `… [${value.length - i} more items omitted to fit the response size limit]`
            out.push(marker)
            cost += marker.length + 3
        }
        return { value: out, cost }
    }
    if (isRecord(value)) {
        const out: Record<string, unknown> = {}
        let cost = 2 // "{}"
        const entries = Object.entries(value)
        let i = 0
        for (; i < entries.length; i++) {
            const [key, val] = entries[i]!
            if (budget - cost < MIN_ITEM_BUDGET) {
                break
            }
            const child = compactValue(val, budget - cost - key.length - META_RESERVE)
            assignKey(out, key, child.value)
            cost += key.length + 3 + child.cost + 1 // "key":value,
        }
        if (i < entries.length) {
            assignKey(out, '_omittedKeys', entries.length - i)
            cost += 24
        }
        return { value: out, cost }
    }
    return { value, cost: 0 }
}

/**
 * Compact a single trace to fit `budget` characters. Non-event fields are
 * budgeted first (so a huge `inputState` can't starve the events), then events
 * are filled in until the budget runs out; the first event is compacted to fit
 * rather than kept verbatim, so no single event can breach the cap. Dropped
 * events are reported via `_truncated`.
 *
 * Events are dropped from the tail. The backend orders events by timestamp,
 * which is not guaranteed to be parent-before-child order, so a truncated trace
 * may not be fully tree-reconstructable — hence the pointer back to PostHog.
 */
export function compactTrace(trace: unknown, budget: number = MAX_TRACE_CHARS): unknown {
    if (!isRecord(trace)) {
        return trace
    }
    const events = Array.isArray(trace.events) ? trace.events : null
    if (!events) {
        return compactValue(trace, budget).value
    }

    const rest: Record<string, unknown> = {}
    for (const [key, val] of Object.entries(trace)) {
        if (key !== 'events') {
            assignKey(rest, key, val)
        }
    }
    const baseCompacted = compactValue(rest, Math.max(0, budget - EVENTS_RESERVE))
    const base = baseCompacted.value as Record<string, unknown>

    let remaining = budget - baseCompacted.cost - META_RESERVE
    const kept: unknown[] = []
    let i = 0
    for (; i < events.length; i++) {
        if (kept.length >= 1 && remaining < MIN_ITEM_BUDGET) {
            break
        }
        const child = compactValue(events[i], Math.max(MIN_ITEM_BUDGET, remaining))
        kept.push(child.value)
        remaining -= child.cost + 1
    }

    assignKey(base, 'events', kept)
    const omitted = events.length - kept.length
    if (omitted > 0) {
        assignKey(base, '_truncated', {
            omittedEvents: omitted,
            totalEvents: events.length,
            reason: 'Trace exceeded the response size limit; some events were dropped and large values were shortened.',
            note: 'Open the trace in PostHog for the complete, untruncated data, or narrow the query to the events you need.',
        })
    }
    return base
}

/**
 * Compact the `results` array from a trace query. `query-llm-trace` returns a
 * single trace, which gets the full per-trace budget. `query-llm-traces-list`
 * returns many traces, so a single total budget is shared across them and
 * trailing traces beyond it are dropped and flagged — without this an entire
 * page of individually-bounded traces could still add up to tens of megabytes.
 */
export function compactTraceResults(results: unknown): unknown {
    if (!Array.isArray(results)) {
        return results
    }
    if (results.length <= 1) {
        return results.map((trace) => compactTrace(trace, MAX_TRACE_CHARS))
    }

    const out: unknown[] = []
    let remaining = MAX_TRACE_CHARS
    let i = 0
    for (; i < results.length; i++) {
        if (out.length >= 1 && remaining < MIN_TRACE_BUDGET) {
            break
        }
        const compacted = compactTrace(results[i], Math.min(MAX_TRACE_CHARS, Math.max(MIN_TRACE_BUDGET, remaining)))
        out.push(compacted)
        remaining -= serializedLength(compacted) + 1
    }
    const omitted = results.length - i
    if (omitted > 0) {
        out.push({
            _truncated: {
                omittedTraces: omitted,
                totalTraces: results.length,
                reason: 'The combined trace list exceeded the response size limit.',
                note: 'Narrow the query (shorter date range, more filters, or a smaller limit), or fetch individual traces with query-llm-trace.',
            },
        })
    }
    return out
}
