import { dayjs } from 'lib/dayjs'

import type { _TracingTraceAiEventApi } from './generated/api.schemas'
import type { Span } from './types'

export type TraceAiEvent = _TracingTraceAiEventApi

/** The service name synthetic AI rows carry, so they get one color and one label in the waterfall. */
export const AI_EVENT_SERVICE_NAME = 'llm'

/** Matches `MAX_AI_EVENTS_PER_TRACE` in the backend lookup, which returns at most this many events. */
export const MAX_AI_EVENTS_PER_TRACE = 500

const AI_SPAN_ID_PREFIX = 'ai:'
const SPAN_KIND_CLIENT = 3

export function isAiEventSpan(span: Span): boolean {
    return span.span_id.startsWith(AI_SPAN_ID_PREFIX)
}

interface Interval {
    startMs: number
    endMs: number
}

interface ParentCandidates {
    byId: Map<string, Span>
    intervals: (Interval & { span: Span })[]
}

function spanInterval(span: Span): Interval {
    const startMs = dayjs(span.timestamp).valueOf()
    return { startMs, endMs: startMs + span.duration_nano / 1_000_000 }
}

function aiEventInterval(event: TraceAiEvent): Interval {
    const startMs = dayjs(event.started_at).valueOf()
    const latencyMs = Math.max(event.latency_seconds ?? 0, 0) * 1000
    return { startMs, endMs: startMs + latencyMs }
}

/**
 * The real span the AI event belongs under. An OpenTelemetry-sourced event names its parent span,
 * so that wins when the span is loaded. Otherwise the narrowest real span whose time range
 * contains the event, so a model call lands under the turn or request that made it.
 */
function findParentSpan(event: TraceAiEvent, candidates: ParentCandidates, interval: Interval): Span | null {
    const parentId = event.ai_parent_id?.toLowerCase()
    const named = parentId ? candidates.byId.get(parentId) : undefined
    if (named) {
        return named
    }
    let best: Span | null = null
    let bestDurationNano = Number.POSITIVE_INFINITY
    for (const { span, startMs, endMs } of candidates.intervals) {
        if (startMs <= interval.startMs && endMs >= interval.endMs && span.duration_nano < bestDurationNano) {
            best = span
            bestDurationNano = span.duration_nano
        }
    }
    return best
}

// Parse each span once, not once per AI event, because a trace can load thousands of spans.
function parentCandidates(spans: Span[]): ParentCandidates {
    const byId = new Map<string, Span>()
    for (const span of spans) {
        const id = span.span_id.toLowerCase()
        if (!byId.has(id)) {
            byId.set(id, span)
        }
    }
    return { byId, intervals: spans.map((span) => ({ span, ...spanInterval(span) })) }
}

/**
 * Map each AI event to the loaded AI event its `ai_parent_id` names, when no real span has that id.
 * OpenTelemetry AI ingestion writes a wrapper span such as `ai.generateText` as an `$ai_span`
 * event, and the model call under it names that event's span id as its parent.
 */
function findAiParents(events: TraceAiEvent[], realSpanIds: Set<string>): Map<string, string> {
    const uuidBySpanId = new Map<string, string>()
    for (const event of events) {
        if (event.ai_span_id) {
            uuidBySpanId.set(event.ai_span_id.toLowerCase(), event.uuid)
        }
    }
    const parents = new Map<string, string>()
    for (const event of events) {
        const parentId = event.ai_parent_id?.toLowerCase()
        const parentUuid = parentId && !realSpanIds.has(parentId) ? uuidBySpanId.get(parentId) : undefined
        if (parentUuid) {
            parents.set(event.uuid, parentUuid)
        }
    }
    // The waterfall drops every row on a parent loop, so a self-parented or cyclic event falls back to
    // time containment instead.
    return new Map([...parents].filter(([uuid]) => !isOnCycle(uuid, parents)))
}

function isOnCycle(uuid: string, parents: Map<string, string>): boolean {
    const seen = new Set<string>()
    for (let current = parents.get(uuid); current !== undefined && !seen.has(current); current = parents.get(current)) {
        if (current === uuid) {
            return true
        }
        seen.add(current)
    }
    return false
}

function eventName(event: TraceAiEvent): string {
    if (event.event === '$ai_span') {
        return event.span_name ?? 'span'
    }
    return event.model ?? event.event
}

function eventAttributes(event: TraceAiEvent): Record<string, string> {
    const attributes: Record<string, string> = { 'ai.event': event.event }
    const optional: Record<string, string | number | null | undefined> = {
        'ai.model': event.model,
        'ai.provider': event.provider,
        'ai.input_tokens': event.input_tokens,
        'ai.output_tokens': event.output_tokens,
        'ai.total_cost_usd': event.total_cost_usd,
        'ai.trace_id': event.ai_trace_id,
        'ai.span_id': event.ai_span_id,
        'ai.parent_id': event.ai_parent_id,
    }
    for (const [key, value] of Object.entries(optional)) {
        if (value !== null && value !== undefined) {
            attributes[key] = String(value)
        }
    }
    return attributes
}

/**
 * Turn a trace's AI events into spans the waterfall can draw next to the real ones. Each row sits
 * under the real span or AI event its parent id names, or else under the real span that contains
 * it in time, because the two datasets share a trace id but often no span ids.
 */
export function buildAiEventSpans(events: TraceAiEvent[], spans: Span[]): Span[] {
    if (events.length === 0 || spans.length === 0) {
        return []
    }
    const traceId = spans[0].trace_id
    const candidates = parentCandidates(spans.filter((span) => !isAiEventSpan(span)))
    const aiParents = findAiParents(events, new Set(candidates.byId.keys()))
    return events.map((event): Span => {
        const interval = aiEventInterval(event)
        const aiParentUuid = aiParents.get(event.uuid)
        const parentSpanId = aiParentUuid
            ? `${AI_SPAN_ID_PREFIX}${aiParentUuid}`
            : (findParentSpan(event, candidates, interval)?.span_id ?? '')
        return {
            uuid: event.uuid,
            trace_id: traceId,
            span_id: `${AI_SPAN_ID_PREFIX}${event.uuid}`,
            parent_span_id: parentSpanId,
            name: eventName(event),
            kind: SPAN_KIND_CLIENT,
            service_name: AI_EVENT_SERVICE_NAME,
            status_code: event.is_error ? 2 : 1,
            timestamp: dayjs(interval.startMs).toISOString(),
            end_time: dayjs(interval.endMs).toISOString(),
            duration_nano: (interval.endMs - interval.startMs) * 1_000_000,
            is_root_span: false,
            matched_filter: true,
            attributes: eventAttributes(event),
            resource_attributes: {},
        }
    })
}
