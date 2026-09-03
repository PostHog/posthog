/**
 * Bounds the size of LLM trace results before they are serialized toward the MCP
 * client. `query-llm-trace` returns every event in a trace at every nesting
 * depth, and each event carries its full `properties` — entire LLM prompts,
 * completions, and tool payloads. Left unbounded these responses have reached
 * tens of millions of tokens, which exhausts the calling agent's context window.
 *
 * Two layers keep that in check. `summary` detail replaces event content with
 * short previews so the default response is trace metadata plus enough of each
 * prompt and output to decide what to read next. On top of that, compaction
 * walks the result within a character budget, truncating long string values and
 * dropping content that doesn't fit, and stops traversing once the budget is
 * spent so it never materializes a full clone of a pathological trace. A final
 * pass measures the real encoded output and shrinks again if the walk's estimate
 * was wrong, so the response cannot breach the cap.
 *
 * Compaction is a client-boundary safeguard only — the underlying query and the
 * PostHog UI still have the complete, untruncated trace. Everything it shortens
 * or drops is flagged so the agent knows to ask for `detail: "full"` or open the
 * trace in PostHog.
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

/**
 * Cap for `summary` detail (~30K tokens). Much tighter than the full-detail cap,
 * because the point of a summary is to survey a trace without spending the
 * agent's context on prompt and completion bodies.
 */
export const MAX_SUMMARY_CHARS = 120_000

/** How much of each previewed value a summary keeps. */
export const SUMMARY_PREVIEW_CHARS = 600

/**
 * How much of an event's content reaches the client. `summary` keeps identity,
 * timing, model, cost, tool, and error metadata verbatim and previews everything
 * else. `full` keeps all properties, bounded by the compaction budget.
 */
export type TraceDetail = 'summary' | 'full'

// Share of the budget the non-event trace fields may spend, so an oversized
// `inputState`/`outputState` can't starve the events out entirely. A ratio rather
// than a fixed reserve, because a fixed one leaves nothing for `id` and the other
// identity fields once a trace's share of a list budget drops below it.
const BASE_FIELDS_BUDGET_RATIO = 0.9
// Room reserved for the `_truncated` metadata object.
const META_RESERVE = 500
// Below this remaining budget we stop adding more items rather than emit useless
// fragments. Also the floor budget handed to a forced-keep first event.
const MIN_ITEM_BUDGET = 256
// Both allowances are sized for the full-trace budget. A preview budget is three
// orders of magnitude smaller, where a flat reserve and a flat floor consume the
// whole allowance and every nested value comes back empty, so scale them down
// with the budget once it gets that small.
const SMALL_BUDGET_RESERVE_RATIO = 0.1
const SMALL_BUDGET_MIN_ITEM_RATIO = 0.25

// Smallest budget a trace may get in a multi-trace (list) response.
const MIN_TRACE_BUDGET = 2_000
// How many times the encoded-size check may re-run the walk with a smaller
// budget before it gives up and returns the minimal placeholder.
const MAX_FIT_PASSES = 4
// Extra shrink applied on each re-run so a pass lands inside the cap instead of
// converging on it one percent at a time.
const FIT_HEADROOM = 1.2

/**
 * Event properties that stay verbatim in a summary. These are the fields an
 * agent needs to navigate a trace: tree position, timing, model, spend, tool
 * calls, and failures. Everything else is content and gets previewed.
 */
const SUMMARY_METADATA_PROPERTIES = new Set([
    '$ai_trace_id',
    '$ai_span_id',
    '$ai_generation_id',
    '$ai_parent_id',
    '$ai_span_name',
    '$ai_session_id',
    '$ai_model',
    '$ai_provider',
    '$ai_latency',
    '$ai_input_tokens',
    '$ai_output_tokens',
    '$ai_cache_read_input_tokens',
    '$ai_reasoning_tokens',
    '$ai_input_cost_usd',
    '$ai_output_cost_usd',
    '$ai_total_cost_usd',
    '$ai_tools_called',
    '$ai_is_error',
    '$ai_error',
    '$ai_http_status',
    '$ai_metric_name',
    '$ai_metric_value',
    '$ai_feedback_text',
])

/** Trace-level fields that carry conversation content rather than metadata. */
const SUMMARY_PREVIEWED_TRACE_FIELDS = new Set(['inputState', 'outputState'])

const SUMMARY_NOTE =
    'Event content is previewed. Re-run this tool with detail: "full" for complete prompts, outputs, and custom properties, or open the trace in PostHog.'

function metaReserveFor(budget: number): number {
    return Math.min(META_RESERVE, Math.floor(Math.max(0, budget) * SMALL_BUDGET_RESERVE_RATIO))
}

function minItemBudgetFor(budget: number): number {
    return Math.min(MIN_ITEM_BUDGET, Math.floor(Math.max(0, budget) * SMALL_BUDGET_MIN_ITEM_RATIO))
}

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
 * Length of a string once encoded as a JSON value, including its quotes. JSON
 * escaping can multiply a value's size several times over: a quote or a newline
 * costs two characters, and a control character costs six. Budgeting on the raw
 * character count let a trace of escape-heavy text serialize to several times
 * the cap.
 */
function encodedStringLength(value: string): number {
    return JSON.stringify(value).length
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
    const cap = Math.max(0, budget)
    if (value.length <= PER_VALUE_CHAR_LIMIT && encodedStringLength(value) <= cap) {
        return value
    }
    let kept = value.slice(0, Math.min(PER_VALUE_CHAR_LIMIT, value.length))
    // Shrink by the measured overshoot rather than by a character count, because
    // escaping decides how much of the budget each character actually costs.
    while (kept.length > 0) {
        const encoded = encodedStringLength(kept)
        if (encoded <= cap) {
            break
        }
        const shrunkTo = cap <= 0 ? 0 : Math.floor(kept.length / ((encoded / cap) * FIT_HEADROOM))
        kept = kept.slice(0, Math.min(shrunkTo, kept.length - 1))
    }
    if (kept.length >= value.length) {
        return value
    }
    const dropped = value.length - kept.length
    return `${kept}… [truncated ${dropped} of ${value.length} chars — open the trace in PostHog for the full value]`
}

interface Compacted {
    value: unknown
    /** Serialized length of `value`, measured for strings and keys. */
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
        return { value: out, cost: encodedStringLength(out) }
    }
    const reserve = metaReserveFor(budget)
    const minItemBudget = minItemBudgetFor(budget)
    if (Array.isArray(value)) {
        const out: unknown[] = []
        let cost = 2 // "[]"
        let i = 0
        for (; i < value.length; i++) {
            if (budget - cost < minItemBudget) {
                break
            }
            const child = compactValue(value[i], budget - cost - reserve)
            out.push(child.value)
            cost += child.cost + 1 // + comma
        }
        if (i < value.length) {
            const marker = `… [${value.length - i} more items omitted to fit the response size limit]`
            out.push(marker)
            cost += encodedStringLength(marker) + 1
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
            // The key itself is unbounded input (arbitrary parsed JSON), so charge
            // its serialized size against the budget before admitting the member —
            // otherwise a single ~1MB property name slips past the cap even after
            // its value is compacted to nothing.
            const keyCost = encodedStringLength(key) + 1 // "key":
            if (budget - cost - keyCost < minItemBudget) {
                break
            }
            const child = compactValue(val, budget - cost - keyCost - reserve)
            assignKey(out, key, child.value)
            cost += keyCost + child.cost + 1 // "key":value,
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
 * Re-measure the encoded output and re-run the walk with a smaller budget while
 * it still exceeds the cap. The walk budgets an estimate of the encoded size, so
 * an estimate that is wrong for one payload shape would otherwise reach the
 * client as an oversized frame. This measures the compacted output only, never
 * the raw input, so the check itself stays cheap.
 */
function fitToEncodedBudget(budget: number, compact: (walkBudget: number) => unknown, fallback: unknown): unknown {
    let walkBudget = budget
    let out = compact(walkBudget)
    for (let pass = 0; pass < MAX_FIT_PASSES; pass++) {
        const encoded = serializedLength(out)
        if (encoded <= budget) {
            return out
        }
        walkBudget = Math.max(MIN_ITEM_BUDGET, Math.floor((walkBudget * budget) / encoded / FIT_HEADROOM))
        out = compact(walkBudget)
    }
    return serializedLength(out) <= budget ? out : fallback
}

/** Shorten one value to a preview an agent can scan without reading it in full. */
function previewValue(value: unknown): unknown {
    return compactValue(value, SUMMARY_PREVIEW_CHARS).value
}

function summarizeEvent(event: unknown): unknown {
    if (!isRecord(event)) {
        return previewValue(event)
    }
    const out: Record<string, unknown> = {}
    for (const [key, value] of Object.entries(event)) {
        if (key !== 'properties' || !isRecord(value)) {
            assignKey(out, key, value)
            continue
        }
        const properties: Record<string, unknown> = {}
        for (const [propertyKey, propertyValue] of Object.entries(value)) {
            assignKey(
                properties,
                propertyKey,
                SUMMARY_METADATA_PROPERTIES.has(propertyKey) ? propertyValue : previewValue(propertyValue)
            )
        }
        assignKey(out, 'properties', properties)
    }
    return out
}

/** Preview the trace-level fields that carry conversation content. */
function summarizeTraceFields(fields: Record<string, unknown>): void {
    for (const key of SUMMARY_PREVIEWED_TRACE_FIELDS) {
        if (key in fields) {
            assignKey(fields, key, previewValue(fields[key]))
        }
    }
    assignKey(fields, '_detail', { mode: 'summary', note: SUMMARY_NOTE })
}

/**
 * Compact a single trace to fit `budget` characters, previewing event content
 * first when `detail` is `summary`. Non-event fields are
 * budgeted first (so a huge `inputState` can't starve the events), then events
 * are filled in until the budget runs out; the first event is compacted to fit
 * rather than kept verbatim, so no single event can breach the cap. Dropped
 * events are reported via `_truncated`.
 *
 * Events are dropped from the tail. The backend orders events by timestamp,
 * which is not guaranteed to be parent-before-child order, so a truncated trace
 * may not be fully tree-reconstructable — hence the pointer back to PostHog.
 */
export function compactTrace(trace: unknown, budget: number = MAX_TRACE_CHARS, detail: TraceDetail = 'full'): unknown {
    if (!isRecord(trace)) {
        return trace
    }
    return fitToEncodedBudget(
        budget,
        (walkBudget) => compactTraceWithin(trace, walkBudget, detail),
        minimalTracePlaceholder(trace)
    )
}

function compactTraceWithin(trace: Record<string, unknown>, budget: number, detail: TraceDetail): unknown {
    const events = Array.isArray(trace.events) ? trace.events : null

    const rest: Record<string, unknown> = {}
    for (const [key, val] of Object.entries(trace)) {
        if (key !== 'events') {
            assignKey(rest, key, val)
        }
    }
    if (detail === 'summary') {
        summarizeTraceFields(rest)
    }
    if (!events) {
        return compactValue(rest, budget).value
    }
    const baseCompacted = compactValue(rest, Math.max(0, budget * BASE_FIELDS_BUDGET_RATIO))
    const base = baseCompacted.value as Record<string, unknown>

    let remaining = budget - baseCompacted.cost - META_RESERVE
    const kept: unknown[] = []
    let i = 0
    for (; i < events.length; i++) {
        if (kept.length >= 1 && remaining < MIN_ITEM_BUDGET) {
            break
        }
        // Summarize inside the loop so events past the budget are never visited.
        // Summarizing the whole trace up front would build a second copy of a
        // payload that is already large enough to be the problem.
        const event = detail === 'summary' ? summarizeEvent(events[i]) : events[i]
        const child = compactValue(event, Math.max(MIN_ITEM_BUDGET, remaining))
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

/** What a trace collapses to when even the smallest walk budget doesn't fit. */
function minimalTracePlaceholder(trace: Record<string, unknown>): Record<string, unknown> {
    const events = Array.isArray(trace.events) ? trace.events : []
    return {
        ...(typeof trace.id === 'string' ? { id: trace.id } : {}),
        events: [],
        _truncated: {
            omittedEvents: events.length,
            totalEvents: events.length,
            reason: 'Trace could not be compacted below the response size limit.',
            note: 'Open the trace in PostHog for the complete, untruncated data, or narrow the query to the events you need.',
        },
    }
}

/**
 * Compact the `results` array from a trace query. `query-llm-trace` returns a
 * single trace, which gets the full per-trace budget. `query-llm-traces-list`
 * returns many traces, so a single total budget is shared across them and
 * trailing traces beyond it are dropped and flagged — without this an entire
 * page of individually-bounded traces could still add up to tens of megabytes.
 */
export function compactTraceResults(results: unknown, detail: TraceDetail = 'full'): unknown {
    if (!Array.isArray(results)) {
        return results
    }
    const budget = detail === 'summary' ? MAX_SUMMARY_CHARS : MAX_TRACE_CHARS
    if (results.length <= 1) {
        return results.map((trace) => compactTrace(trace, budget, detail))
    }
    return fitToEncodedBudget(budget, (walkBudget) => compactTraceList(results, walkBudget, detail), [
        listTruncationSentinel(results.length, results.length),
    ])
}

function compactTraceList(results: unknown[], budget: number, detail: TraceDetail): unknown[] {
    const out: unknown[] = []
    let remaining = budget
    let i = 0
    for (; i < results.length; i++) {
        if (out.length >= 1 && remaining < MIN_TRACE_BUDGET) {
            break
        }
        const compacted = compactTrace(results[i], Math.min(budget, Math.max(MIN_TRACE_BUDGET, remaining)), detail)
        out.push(compacted)
        remaining -= serializedLength(compacted) + 1
    }
    const omitted = results.length - i
    if (omitted > 0) {
        out.push(listTruncationSentinel(omitted, results.length))
    }
    return out
}

function listTruncationSentinel(omitted: number, total: number): Record<string, unknown> {
    return {
        _truncated: {
            omittedTraces: omitted,
            totalTraces: total,
            reason: 'The combined trace list exceeded the response size limit.',
            note: 'Narrow the query (shorter date range, more filters, or a smaller limit), or fetch individual traces with query-llm-trace.',
        },
    }
}
