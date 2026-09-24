import { dayjs } from 'lib/dayjs'

import type { _TracingTraceAiEventApi } from './generated/api.schemas'
import type { Span } from './types'

export type TraceAiEvent = _TracingTraceAiEventApi

/** The service name synthetic AI rows carry, so they get one color and one label in the waterfall. */
export const AI_EVENT_SERVICE_NAME = 'llm'

const AI_SPAN_ID_PREFIX = 'ai:'
const SPAN_KIND_CLIENT = 3

export function isAiEventSpan(span: Span): boolean {
    return span.span_id.startsWith(AI_SPAN_ID_PREFIX)
}

interface Interval {
    startMs: number
    endMs: number
}

function spanInterval(span: Span): Interval {
    const startMs = dayjs(span.timestamp).valueOf()
    return { startMs, endMs: startMs + span.duration_nano / 1_000_000 }
}

// The AI event records when the call finished and how long it took; the row starts that far back.
function aiEventInterval(event: TraceAiEvent): Interval {
    const endMs = dayjs(event.timestamp).valueOf()
    const latencyMs = Math.max(event.latency_seconds ?? 0, 0) * 1000
    return { startMs: endMs - latencyMs, endMs }
}

/**
 * The real span the AI event belongs under. An OpenTelemetry-sourced event names its parent span,
 * so that wins when the span is loaded. Otherwise the narrowest real span whose time range
 * contains the event, so a model call lands under the turn or request that made it.
 */
function findParentSpan(event: TraceAiEvent, spans: Span[], interval: Interval): Span | null {
    const parentId = event.ai_parent_id?.toLowerCase()
    const named = parentId ? spans.find((span) => span.span_id.toLowerCase() === parentId) : undefined
    if (named) {
        return named
    }
    let best: Span | null = null
    let bestDurationNano = Number.POSITIVE_INFINITY
    for (const span of spans) {
        const { startMs, endMs } = spanInterval(span)
        if (startMs <= interval.startMs && endMs >= interval.endMs && span.duration_nano < bestDurationNano) {
            best = span
            bestDurationNano = span.duration_nano
        }
    }
    return best
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
 * Turn a trace's AI events into spans the waterfall can draw next to the real ones. Each row is
 * placed by time and parented to the real span that contains it, because the two datasets share
 * a trace id but no span ids.
 */
export function buildAiEventSpans(events: TraceAiEvent[], spans: Span[]): Span[] {
    if (events.length === 0 || spans.length === 0) {
        return []
    }
    const traceId = spans[0].trace_id
    const realSpans = spans.filter((span) => !isAiEventSpan(span))
    return events.map((event): Span => {
        const interval = aiEventInterval(event)
        const parent = findParentSpan(event, realSpans, interval)
        return {
            uuid: event.uuid,
            trace_id: traceId,
            span_id: `${AI_SPAN_ID_PREFIX}${event.uuid}`,
            parent_span_id: parent?.span_id ?? '',
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
