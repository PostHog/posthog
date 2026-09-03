import { makeSpan } from './__mocks__/span'
import { resolveTraceIdentity, type TraceIdentity } from './traceIdentity'
import type { Span } from './types'

describe('resolveTraceIdentity', () => {
    const cases: {
        name: string
        spans: Span[]
        distinctIdKeys?: string[]
        sessionIdKeys?: string[]
        expected: TraceIdentity
    }[] = [
        {
            name: 'reads an identity carried only by a non-root span',
            spans: [
                makeSpan({ span_id: 'root', is_root_span: true }),
                makeSpan({
                    span_id: 'child',
                    is_root_span: false,
                    attributes: { posthogDistinctId: 'user-1', sessionId: 'session-1' },
                }),
            ],
            expected: { distinctId: 'user-1', sessionId: 'session-1' },
        },
        {
            name: 'drops a value the spans disagree on, and keeps the one they agree on',
            spans: [
                makeSpan({ span_id: 'a', attributes: { posthogDistinctId: 'user-1', sessionId: 'session-1' } }),
                makeSpan({ span_id: 'b', attributes: { posthogDistinctId: 'user-2', sessionId: 'session-1' } }),
            ],
            expected: { distinctId: null, sessionId: 'session-1' },
        },
        {
            name: 'resolves nothing from spans that carry no correlation keys',
            spans: [makeSpan({ attributes: { 'http.method': 'GET' }, resource_attributes: { 'k8s.pod.name': 'p' } })],
            expected: { distinctId: null, sessionId: null },
        },
        {
            name: 'prefers a configured key over a convention key on the same span',
            spans: [makeSpan({ attributes: { 'user.id': 'configured-user', posthogDistinctId: 'convention-user' } })],
            distinctIdKeys: ['user.id'],
            expected: { distinctId: 'configured-user', sessionId: null },
        },
        {
            name: 'falls back to resource attributes when the span attributes carry nothing',
            spans: [makeSpan({ resource_attributes: { posthogDistinctId: 'user-1', sessionId: 'session-1' } })],
            expected: { distinctId: 'user-1', sessionId: 'session-1' },
        },
        {
            // A configured key naming an Object.prototype member would otherwise resolve to that
            // member, which is truthy, and reach PersonDisplay as a function instead of a string.
            name: 'ignores a configured key that names an Object.prototype member',
            spans: [makeSpan({ attributes: { posthogDistinctId: 'user-1' } })],
            distinctIdKeys: ['constructor'],
            sessionIdKeys: ['valueOf'],
            expected: { distinctId: 'user-1', sessionId: null },
        },
    ]

    test.each(cases)('$name', ({ spans, distinctIdKeys, sessionIdKeys, expected }) => {
        expect(resolveTraceIdentity(spans, distinctIdKeys, sessionIdKeys)).toEqual(expected)
    })
})
