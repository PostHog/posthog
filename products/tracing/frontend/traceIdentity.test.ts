import { resolveTraceIdentity, type TraceIdentity } from './traceIdentity'
import type { Span } from './types'

function span(overrides: Partial<Span>): Span {
    return {
        uuid: 'uuid',
        trace_id: 'trace-1',
        span_id: 'span-1',
        parent_span_id: '',
        name: 'GET /checkout',
        kind: 2,
        service_name: 'checkout-api',
        status_code: 0,
        timestamp: '2026-09-03T10:00:00Z',
        end_time: '2026-09-03T10:00:01Z',
        duration_nano: 1_000_000,
        is_root_span: true,
        matched_filter: true,
        attributes: {},
        resource_attributes: {},
        ...overrides,
    }
}

describe('resolveTraceIdentity', () => {
    const cases: [
        name: string,
        spans: Span[],
        configuredDistinctIdKeys: string[] | undefined,
        configuredSessionIdKeys: string[] | undefined,
        expected: TraceIdentity,
    ][] = [
        [
            'reads an identity carried only by a non-root span',
            [
                span({ span_id: 'root', is_root_span: true }),
                span({
                    span_id: 'child',
                    is_root_span: false,
                    attributes: { posthogDistinctId: 'user-1', sessionId: 'session-1' },
                }),
            ],
            undefined,
            undefined,
            { distinctId: 'user-1', sessionId: 'session-1' },
        ],
        [
            // Two people in one trace, which a batch consumer produces. The person must drop out
            // rather than pick a side, while the agreeing session still resolves.
            'drops a value the loaded spans disagree on, and keeps the one they agree on',
            [
                span({ span_id: 'a', attributes: { posthogDistinctId: 'user-1', sessionId: 'session-1' } }),
                span({ span_id: 'b', attributes: { posthogDistinctId: 'user-2', sessionId: 'session-1' } }),
            ],
            undefined,
            undefined,
            { distinctId: null, sessionId: 'session-1' },
        ],
        [
            'resolves nothing from spans that carry no correlation keys',
            [span({ attributes: { 'http.method': 'GET' }, resource_attributes: { 'k8s.pod.name': 'pod-1' } })],
            undefined,
            undefined,
            { distinctId: null, sessionId: null },
        ],
        [
            'prefers a configured key over a convention key on the same span',
            [span({ attributes: { 'user.id': 'configured-user', posthogDistinctId: 'convention-user' } })],
            ['user.id'],
            undefined,
            { distinctId: 'configured-user', sessionId: null },
        ],
        [
            'falls back to resource attributes when the span attributes carry nothing',
            [span({ resource_attributes: { posthogDistinctId: 'user-1', sessionId: 'session-1' } })],
            undefined,
            undefined,
            { distinctId: 'user-1', sessionId: 'session-1' },
        ],
    ]

    test.each(cases)('%s', (_name, spans, configuredDistinctIdKeys, configuredSessionIdKeys, expected) => {
        expect(resolveTraceIdentity(spans, configuredDistinctIdKeys, configuredSessionIdKeys)).toEqual(expected)
    })
})
