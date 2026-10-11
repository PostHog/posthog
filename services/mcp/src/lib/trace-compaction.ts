/**
 * Bounds the size of LLM trace results before they are serialized toward the MCP
 * client. `query-llm-trace` returns every event in a trace at every nesting
 * depth, and each event carries its full `properties` — entire LLM prompts,
 * completions, and tool payloads. Left unbounded these responses have reached
 * tens of millions of tokens, which exhausts the calling agent's context window.
 *
 * Two layers keep that in check. `summary` detail leaves event content out
 * altogether and reports the omitted names, so the summary response is trace and
 * event metadata an agent reads to decide what to open. On top of that, compaction
 * walks the result within a character budget, truncating long string values and
 * dropping content that doesn't fit, and stops traversing once the budget is
 * spent so it never materializes a full clone of a pathological trace. A final
 * pass measures the text the client actually receives and shrinks again if the
 * walk's estimate was wrong, so the response cannot breach the cap.
 *
 * Clients can truncate oversized responses or replace them with file references.
 * Truncating here keeps the response parseable and says what was dropped.
 *
 * Compaction is a client-boundary safeguard only — the underlying query and the
 * PostHog UI still have the complete, untruncated trace. Everything it shortens
 * or drops is flagged so the agent can narrow the query or open the trace in
 * PostHog.
 */

import { MCP_TOOL_OUTPUT_CHAR_BUDGET } from '@/lib/constants'
import { assignKey, isRecord } from '@/lib/plain-object'
import { formatResponse } from '@/lib/response'

/** Longest single string value kept verbatim; longer values are truncated. */
export const PER_VALUE_CHAR_LIMIT = 10_000

export const MAX_TRACE_CHARS = MCP_TOOL_OUTPUT_CHAR_BUDGET

/**
 * Cap for `summary` detail. Tighter than the full-detail cap,
 * because the point of a summary is to survey a trace without spending the
 * agent's context on prompt and completion bodies.
 */
export const MAX_SUMMARY_CHARS = 60_000

/**
 * How much of an event's content reaches the client. `summary` keeps identity,
 * timing, model, cost, tool, and error metadata and omits the content, so a
 * survey of a trace never carries prompts or completions. `full` keeps every
 * retained property, bounded by the compaction budget.
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

// Share of the event budget reserved for the events that show how the trace
// ended: the last generation and failed events. The rest goes to the other events
// in order.
const OUTCOME_EVENTS_BUDGET_RATIO = 0.5
// Room for the IDs of omitted events, so the agent can read them directly.
const OMITTED_EVENT_IDS_MAX_CHARS = 2_000
const OMITTED_EVENT_IDS_BUDGET_RATIO = 0.02

// Smallest budget a trace may get in a multi-trace (list) response.
const MIN_TRACE_BUDGET = 2_000
// How many times the encoded-size check may re-run the walk with a smaller
// budget before it gives up and returns the minimal placeholder.
const MAX_FIT_PASSES = 4
// Extra shrink applied on each re-run so a pass lands inside the cap instead of
// converging on it one percent at a time.
const FIT_HEADROOM = 1.2

/**
 * Event properties that stay in a summary. These are the fields an agent needs
 * to navigate a trace: tree position, timing, model, spend, tool calls, and
 * failures. Everything else is content and is omitted, name only.
 *
 * A name belongs here when its value is a number, a boolean, a short label, or
 * an identifier — never free text and never a document. That is why the cost,
 * token and timing fields are listed one by one rather than taken from the
 * redaction allowlist wholesale: the allowlist is what a trace may return at
 * all, and most of it is the conversation.
 *
 * `$ai_error` and `$ai_feedback_text` are deliberately absent, though they read
 * as metadata. Both are free text a person or a provider wrote, and a provider
 * error routinely quotes the prompt back, so keeping them would put
 * conversation content in the mode that promises none. `$ai_is_error`,
 * `$ai_http_status`, `$ai_error_type` and `$ai_status` stay, so a survey can
 * still find the failures and then read them at `full` detail.
 */
export const SUMMARY_METADATA_PROPERTIES = new Set([
    '$ai_trace_id',
    '$ai_span_id',
    '$ai_generation_id',
    '$ai_parent_id',
    '$ai_span_name',
    '$ai_session_id',
    '$ai_model',
    '$ai_provider',
    '$ai_temperature',
    '$ai_stream',
    '$ai_effort',
    '$ai_latency',
    '$ai_input_tokens',
    '$ai_output_tokens',
    '$ai_cache_read_input_tokens',
    '$ai_reasoning_tokens',
    '$ai_input_cost_usd',
    '$ai_output_cost_usd',
    '$ai_total_cost_usd',
    '$ai_tools_called',
    '$ai_tool_call_count',
    '$ai_is_error',
    '$ai_http_status',
    '$ai_error_type',
    '$ai_status',
    '$ai_stop_reason',
    '$ai_time_to_first_token',
    '$ai_metric_name',
    '$ai_metric_value',
    '$ai_score',
    '$ai_score_max',
    '$ai_score_min',
    '$ai_span_type',
    // Spend. A cost or latency survey is what summary detail is for, so the
    // whole breakdown stays: every token count, every per-token price, and the
    // per-modality costs the total is made of.
    '$ai_max_tokens',
    '$ai_total_tokens',
    '$ai_total_input_tokens',
    '$ai_total_output_tokens',
    '$ai_text_input_tokens',
    '$ai_text_output_tokens',
    '$ai_audio_input_tokens',
    '$ai_audio_output_tokens',
    '$ai_image_input_tokens',
    '$ai_image_output_tokens',
    '$ai_video_input_tokens',
    '$ai_video_output_tokens',
    '$ai_cache_creation_input_tokens',
    '$ai_cache_creation_1h_input_tokens',
    '$ai_cache_creation_5m_input_tokens',
    '$ai_cache_read_audio_tokens',
    '$ai_audio_cost_usd',
    '$ai_image_cost_usd',
    '$ai_video_cost_usd',
    '$ai_web_search_cost_usd',
    '$ai_web_search_count',
    '$ai_web_search_price',
    '$ai_request_cost_usd',
    '$ai_request_count',
    '$ai_request_price',
    '$ai_input_token_price',
    '$ai_output_token_price',
    '$ai_cache_read_token_price',
    '$ai_cache_write_token_price',
    '$ai_cache_write_1h_token_price',
    '$ai_cache_read_cost_usd',
    '$ai_cache_creation_cost_usd',
    '$ai_billable',
    '$ai_cost_passthrough',
    '$ai_cost_model_source',
    '$ai_cost_model_provider',
    '$ai_model_cost_used',
    '$ai_cache_reporting_exclusive',
    '$ai_tokens_source',
])

/** Free-text error fields. At `full` detail they are compacted before other content. */
const EVENT_ERROR_PROPERTIES = new Set(['$ai_error', '$ai_error_normalized'])

/** What a call returned. Compacted before inputs. */
const EVENT_OUTPUT_PROPERTIES = new Set(['$ai_output_choices', '$ai_output', '$ai_output_state'])

/** Prompts and tool schemas. Usually the largest content, so compacted last. */
const EVENT_BULK_INPUT_PROPERTIES = new Set(['$ai_input', '$ai_input_state', '$ai_tools'])

/** Trace-level fields that carry conversation content rather than metadata. */
const SUMMARY_OMITTED_TRACE_FIELDS = new Set(['inputState', 'outputState'])

/**
 * Names of the content fields a summary leaves out, reported in place of their
 * values. It sits beside `properties` rather than inside it, so it cannot
 * collide with a captured property of the same name.
 */
const SUMMARY_OMITTED_KEYS_FIELD = '_summaryOmittedKeys'

const SUMMARY_NOTE =
    'Event content is omitted; only the names of the omitted properties are listed. Re-run this tool with detail: "full" for prompts, outputs, error messages, and feedback text, or open the trace in PostHog.'

function metaReserveFor(budget: number): number {
    return Math.min(META_RESERVE, Math.floor(Math.max(0, budget) * SMALL_BUDGET_RESERVE_RATIO))
}

function minItemBudgetFor(budget: number): number {
    return Math.min(MIN_ITEM_BUDGET, Math.floor(Math.max(0, budget) * SMALL_BUDGET_MIN_ITEM_RATIO))
}

function serializedLength(value: unknown): number {
    try {
        return JSON.stringify(value).length
    } catch {
        return 0
    }
}

/**
 * Include text-block escaping because clients also use serialized result size
 * to decide whether to replace the content with a file reference.
 */
function deliveredLength(value: unknown, outputFormat?: 'optimized' | 'json'): number {
    const text = outputFormat === 'json' ? JSON.stringify(value) : formatResponse(value)
    // boffin: Measure the complete response so echoed filters cannot bypass the cap.
    return serializedLength([{ type: 'text', text }])
}

/**
 * Character count of a string encoded as a JSON value, including its quotes. JSON
 * escaping can multiply a value's size several times over: a quote or a newline
 * costs two characters, and a control character costs six. Budgeting on the raw
 * character count let a trace of escape-heavy text serialize to several times
 * the cap.
 */
function encodedStringLength(value: string): number {
    return serializedLength(value)
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
        return compactRecord(value, budget)
    }
    return { value, cost: 0 }
}

/**
 * Compact an object member by member. Members are visited in ascending `rank`
 * order, so the members that matter most get the budget first, and the output
 * keeps the original key order. Without a rank, members are visited in key order.
 */
function compactRecord(
    value: Record<string, unknown>,
    budget: number,
    rank?: (key: string) => number,
    compactMember: (key: string, member: unknown, memberBudget: number) => Compacted = (_key, member, memberBudget) =>
        compactValue(member, memberBudget)
): Compacted {
    const reserve = metaReserveFor(budget)
    const minItemBudget = minItemBudgetFor(budget)
    const entries = Object.entries(value)
    const visitOrder = rank ? [...entries].sort(([a], [b]) => rank(a) - rank(b)) : entries
    const kept = new Map<string, unknown>()
    let cost = 2 // "{}"
    let i = 0
    for (; i < visitOrder.length; i++) {
        const [key, val] = visitOrder[i]!
        // The key itself is unbounded input (arbitrary parsed JSON), so charge
        // its serialized size against the budget before admitting the member —
        // otherwise a single ~1MB property name slips past the cap even after
        // its value is compacted to nothing.
        const keyCost = encodedStringLength(key) + 1 // "key":
        if (budget - cost - keyCost < minItemBudget) {
            break
        }
        const child = compactMember(key, val, budget - cost - keyCost - reserve)
        kept.set(key, child.value)
        cost += keyCost + child.cost + 1 // "key":value,
    }
    const out: Record<string, unknown> = {}
    for (const [key] of entries) {
        if (kept.has(key)) {
            assignKey(out, key, kept.get(key))
        }
    }
    if (i < entries.length) {
        assignKey(out, '_omittedKeys', entries.length - i)
        cost += 24
    }
    return { value: out, cost }
}

/**
 * Visit order for event properties. Identity, status, and error fields go first
 * and outputs next, so a long prompt or tool schema cannot crowd out what the
 * call returned or why it failed.
 */
function eventPropertyRank(key: string): number {
    if (SUMMARY_METADATA_PROPERTIES.has(key) || EVENT_ERROR_PROPERTIES.has(key)) {
        return 0
    }
    if (EVENT_OUTPUT_PROPERTIES.has(key)) {
        return 1
    }
    return EVENT_BULK_INPUT_PROPERTIES.has(key) ? 3 : 2
}

/** Visit order for trace fields: identity and totals, then output, then input. */
function traceFieldRank(key: string): number {
    if (key === 'outputState') {
        return 1
    }
    return key === 'inputState' ? 2 : 0
}

function compactEvent(event: unknown, budget: number): Compacted {
    if (!isRecord(event) || !isRecord(event.properties)) {
        return compactValue(event, budget)
    }
    return compactRecord(
        event,
        budget,
        (key) => (key === 'properties' ? 1 : 0),
        (key, member, memberBudget) =>
            key === 'properties' && isRecord(member)
                ? compactRecord(member, memberBudget, eventPropertyRank)
                : compactValue(member, memberBudget)
    )
}

function isFailedEvent(event: unknown): boolean {
    if (!isRecord(event) || !isRecord(event.properties)) {
        return false
    }
    const { $ai_is_error: flag, $ai_error: error } = event.properties
    return flag === true || flag === 'true' || Boolean(error)
}

/**
 * Indexes of the events that show how a trace ended, most important first: the
 * last generation (or the last event when the trace has no generation), then
 * failed events from latest to earliest.
 */
function outcomeEventIndexes(events: unknown[]): number[] {
    let final = -1
    const failed: number[] = []
    for (let i = events.length - 1; i >= 0; i--) {
        const event = events[i]
        if (final === -1 && isRecord(event) && event.event === '$ai_generation') {
            final = i
        }
        if (isFailedEvent(event)) {
            failed.push(i)
        }
    }
    if (final === -1 && events.length > 0) {
        final = events.length - 1
    }
    const indexes = final === -1 ? [] : [final]
    for (const index of failed) {
        if (index !== final) {
            indexes.push(index)
        }
    }
    return indexes
}

/**
 * Re-measure the encoded output and re-run the walk with a smaller budget while
 * it still exceeds the cap. The walk budgets an estimate of the encoded size, so
 * an estimate that is wrong for one payload shape would otherwise reach the
 * client as an oversized frame. This measures the compacted output only, never
 * the raw input, so the check itself stays cheap.
 */
function fitToEncodedBudget<T>(
    budget: number,
    compact: (walkBudget: number) => T,
    fallback: T,
    measure: (value: T) => number = serializedLength
): T {
    let walkBudget = budget
    let out = compact(walkBudget)
    for (let pass = 0; pass < MAX_FIT_PASSES; pass++) {
        const encoded = measure(out)
        if (encoded <= budget) {
            return out
        }
        walkBudget = Math.max(MIN_ITEM_BUDGET, Math.floor((walkBudget * budget) / encoded / FIT_HEADROOM))
        out = compact(walkBudget)
    }
    return measure(out) <= budget ? out : fallback
}

function summarizeEvent(event: unknown): unknown {
    if (!isRecord(event)) {
        return event
    }
    const out: Record<string, unknown> = {}
    const omitted: string[] = []
    for (const [key, value] of Object.entries(event)) {
        if (key !== 'properties' || !isRecord(value)) {
            assignKey(out, key, value)
            continue
        }
        const properties: Record<string, unknown> = {}
        for (const [propertyKey, propertyValue] of Object.entries(value)) {
            if (SUMMARY_METADATA_PROPERTIES.has(propertyKey)) {
                assignKey(properties, propertyKey, propertyValue)
            } else {
                omitted.push(propertyKey)
            }
        }
        assignKey(out, 'properties', properties)
    }
    if (omitted.length > 0) {
        assignKey(out, SUMMARY_OMITTED_KEYS_FIELD, omitted)
    }
    return out
}

/** Leave out the trace-level fields that carry conversation content. */
function summarizeTraceFields(fields: Record<string, unknown>): void {
    const omitted: string[] = []
    for (const key of SUMMARY_OMITTED_TRACE_FIELDS) {
        if (key in fields) {
            delete fields[key]
            omitted.push(key)
        }
    }
    if (omitted.length > 0) {
        assignKey(fields, SUMMARY_OMITTED_KEYS_FIELD, omitted)
    }
    assignKey(fields, '_detail', { mode: 'summary', note: SUMMARY_NOTE })
}

/**
 * Compact a single trace to fit `budget` characters, dropping event content
 * first when `detail` is `summary`. Non-event fields are
 * budgeted first (so a huge `inputState` can't starve the events). Then the
 * last generation and the failed events get a reserved share, and the other
 * events are filled in order until the budget runs out. Each event is compacted
 * to fit rather than kept verbatim, so no single event can breach the cap.
 * Kept events stay in their original order. Dropped events are reported via
 * `_truncated`, with their IDs when they fit.
 *
 * The backend orders events by timestamp, which is not guaranteed to be
 * parent-before-child order, so a truncated trace may not be fully
 * tree-reconstructable — hence the pointer back to PostHog.
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
    const baseCompacted = compactRecord(rest, Math.max(0, budget * BASE_FIELDS_BUDGET_RATIO), traceFieldRank)
    const base = baseCompacted.value as Record<string, unknown>

    const omittedIdsReserve = Math.min(OMITTED_EVENT_IDS_MAX_CHARS, Math.floor(budget * OMITTED_EVENT_IDS_BUDGET_RATIO))
    let remaining = budget - baseCompacted.cost - META_RESERVE - omittedIdsReserve
    const kept = new Map<number, unknown>()
    // Summarize inside the loops so events past the budget are never visited.
    // Summarizing the whole trace up front would build a second copy of a
    // payload that is already large enough to be the problem.
    const keep = (index: number, eventBudget: number): number => {
        const event = detail === 'summary' ? summarizeEvent(events[index]) : events[index]
        const child = compactEvent(event, Math.max(MIN_ITEM_BUDGET, eventBudget))
        kept.set(index, child.value)
        return child.cost + 1
    }

    // Keep the outcome events first, each with an equal share of a capped
    // reserve, so early prompt-heavy events cannot push them out of the response.
    const outcomes = outcomeEventIndexes(events)
    let outcomeRemaining = Math.floor(remaining * OUTCOME_EVENTS_BUDGET_RATIO)
    for (let o = 0; o < outcomes.length; o++) {
        if (kept.size >= 1 && outcomeRemaining < MIN_ITEM_BUDGET) {
            break
        }
        const spent = keep(outcomes[o]!, Math.floor(outcomeRemaining / (outcomes.length - o)))
        outcomeRemaining -= spent
        remaining -= spent
    }

    for (let i = 0; i < events.length; i++) {
        if (kept.has(i)) {
            continue
        }
        if (kept.size >= 1 && remaining < MIN_ITEM_BUDGET) {
            break
        }
        remaining -= keep(i, remaining)
    }

    const keptEvents: unknown[] = []
    const omittedIds: string[] = []
    for (let i = 0; i < events.length; i++) {
        if (kept.has(i)) {
            keptEvents.push(kept.get(i))
        } else {
            const event = events[i]
            if (isRecord(event) && typeof event.id === 'string') {
                omittedIds.push(event.id)
            }
        }
    }
    assignKey(base, 'events', keptEvents)
    const omitted = events.length - kept.size
    if (omitted > 0) {
        const note =
            detail === 'full'
                ? 'Re-run with detail: "summary" for metadata alone. Summary responses can also omit events; read omitted events by ID with SQL, narrow the query, or open the trace in PostHog for the complete data.'
                : 'Read omitted events by ID with SQL, open the trace in PostHog for the complete, untruncated data, or narrow the query to the events you need.'
        assignKey(base, '_truncated', {
            omittedEvents: omitted,
            totalEvents: events.length,
            omittedEventIds: idsWithin(omittedIds, omittedIdsReserve),
            reason: 'Trace exceeded the response size limit; some events were dropped and large values were shortened. The last generation and failed events are kept first.',
            note,
        })
    }
    return base
}

/** The leading IDs whose serialized list fits `budget` characters. */
function idsWithin(ids: string[], budget: number): string[] {
    const out: string[] = []
    let cost = 2 // "[]"
    for (const id of ids) {
        const idCost = encodedStringLength(id) + 1
        if (cost + idCost > budget) {
            break
        }
        out.push(id)
        cost += idCost
    }
    return out
}

/** What a trace collapses to when even the smallest walk budget doesn't fit. */
function minimalTracePlaceholder(trace: Record<string, unknown>): Record<string, unknown> {
    const events = Array.isArray(trace.events) ? trace.events : []
    return {
        ...(typeof trace.id === 'string' ? { id: truncateString(trace.id, MIN_ITEM_BUDGET) } : {}),
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
 * Bound the complete trace response in its selected output format. Echoed
 * filters and warnings share a fifth of the walk budget so they cannot crowd
 * out the trace data. The final check includes serialization overhead.
 */
export function compactTraceResponse(
    response: { results: unknown; [key: string]: unknown },
    detail: TraceDetail = 'full',
    outputFormat?: 'optimized' | 'json'
): Record<string, unknown> {
    const { results, ...envelope } = response
    const budget = detail === 'summary' ? MAX_SUMMARY_CHARS : MAX_TRACE_CHARS
    const traces = Array.isArray(results) ? results : []
    const single = traces.length === 1 && isRecord(traces[0]) ? traces[0] : null
    return fitToEncodedBudget(
        budget,
        (walkBudget) => {
            const base = compactValue(envelope, Math.floor(walkBudget / 5))
            const resultsBudget = Math.max(MIN_TRACE_BUDGET, walkBudget - base.cost)
            return {
                ...(base.value as Record<string, unknown>),
                results: Array.isArray(results)
                    ? compactTraceList(results, resultsBudget, detail)
                    : compactValue(results, resultsBudget).value,
            }
        },
        {
            results: single
                ? [minimalTracePlaceholder(single)]
                : [listTruncationSentinel(traces.length, traces.length)],
        },
        (value) => deliveredLength(value, outputFormat)
    )
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
