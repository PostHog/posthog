import { makeSpan } from './__mocks__/span'
import { buildAiEventSpans, TraceAiEvent } from './aiEventSpans'
import type { Span } from './types'

const TRACE_ID = '4BF92F3577B34DA6A3CE929D0E0E4736'

function span(overrides: Partial<Span> & { span_id: string; timestamp: string; duration_nano: number }): Span {
    return makeSpan({
        uuid: overrides.span_id,
        trace_id: TRACE_ID,
        name: overrides.span_id,
        is_root_span: false,
        ...overrides,
    })
}

function aiEvent(overrides: Partial<TraceAiEvent> & { uuid: string; started_at: string }): TraceAiEvent {
    return {
        event: '$ai_generation',
        ai_trace_id: TRACE_ID.toLowerCase(),
        ai_span_id: null,
        ai_parent_id: null,
        span_name: null,
        latency_seconds: 2,
        model: 'model-x',
        provider: 'provider-y',
        input_tokens: 10,
        output_tokens: 5,
        total_cost_usd: 0.01,
        is_error: false,
        ...overrides,
    }
}

// A run root that lasts a minute, one turn inside it, and one tool call inside the turn.
const ROOT = span({ span_id: 'ROOT', timestamp: '2026-06-02T08:00:00.000Z', duration_nano: 60e9, is_root_span: true })
const TURN = span({
    span_id: 'TURN',
    parent_span_id: 'ROOT',
    timestamp: '2026-06-02T08:00:01.000Z',
    duration_nano: 50e9,
})
const TOOL = span({
    span_id: 'TOOL',
    parent_span_id: 'TURN',
    timestamp: '2026-06-02T08:00:10.000Z',
    duration_nano: 1e9,
})
const SPANS = [ROOT, TURN, TOOL]

describe('buildAiEventSpans', () => {
    // A wrong end or a wrong parent puts the row in the wrong place on the waterfall.
    it('runs the row a latency from its start and parents it to the narrowest containing span', () => {
        const [result] = buildAiEventSpans([aiEvent({ uuid: 'e1', started_at: '2026-06-02T08:00:03.000Z' })], SPANS)

        expect(result).toMatchObject({
            span_id: 'ai:e1',
            parent_span_id: 'TURN',
            timestamp: '2026-06-02T08:00:03.000Z',
            end_time: '2026-06-02T08:00:05.000Z',
            duration_nano: 2e9,
            name: 'model-x',
            status_code: 1,
            attributes: { 'ai.model': 'model-x', 'ai.input_tokens': '10' },
        })
    })

    it.each([
        // An OTel-sourced event names its parent, which wins over time containment.
        ['a named parent that is loaded', { started_at: '2026-06-02T08:00:03.000Z', ai_parent_id: 'tool' }, 'TOOL'],
        ['a named parent that is not loaded', { started_at: '2026-06-02T08:00:03.000Z', ai_parent_id: 'gone' }, 'TURN'],
        // A call that ran past the turn's end is only contained by the root.
        ['a call the turn does not contain', { started_at: '2026-06-02T08:00:45.000Z', latency_seconds: 10 }, 'ROOT'],
        ['a call nothing contains', { started_at: '2026-06-02T08:02:00.000Z' }, ''],
    ])('places %s', (_name, overrides, expectedParent) => {
        const [result] = buildAiEventSpans([aiEvent({ uuid: 'e1', ...overrides })], SPANS)

        expect(result.parent_span_id).toBe(expectedParent)
    })

    it('marks a failed call as an error and names an $ai_span by its span name', () => {
        const results = buildAiEventSpans(
            [
                aiEvent({ uuid: 'e1', started_at: '2026-06-02T08:00:03.000Z', is_error: true }),
                aiEvent({ uuid: 'e2', started_at: '2026-06-02T08:00:04.000Z', event: '$ai_span', span_name: 'plan' }),
            ],
            SPANS
        )

        expect(results.map((r) => [r.status_code, r.name])).toEqual([
            [2, 'model-x'],
            [1, 'plan'],
        ])
    })

    // Merging twice must not parent new rows to earlier synthetic rows or emit rows without a trace.
    it('ignores earlier synthetic rows and returns nothing without real spans', () => {
        const first = buildAiEventSpans([aiEvent({ uuid: 'e1', started_at: '2026-06-02T08:00:03.000Z' })], SPANS)
        const second = buildAiEventSpans(
            [aiEvent({ uuid: 'e2', started_at: '2026-06-02T08:00:04.400Z', latency_seconds: 0.1 })],
            [...SPANS, ...first]
        )

        expect(second[0].parent_span_id).toBe('TURN')
        expect(buildAiEventSpans([aiEvent({ uuid: 'e3', started_at: '2026-06-02T08:00:03.000Z' })], [])).toEqual([])
    })
})
