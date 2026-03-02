import type { LLMTrace, LLMTraceEvent } from '~/queries/schema/schema-general'

import type { EnrichedTraceTreeNode } from './llmAnalyticsTraceDataLogic'
import { findNodeByEventId, hasTraceContent } from './traceViewUtils'

describe('traceViewUtils', () => {
    const baseTrace: LLMTrace = {
        id: 'trace-1',
        createdAt: '2025-01-01T00:00:00Z',
        person: {
            uuid: 'person-1',
            created_at: '2025-01-01T00:00:00Z',
            properties: {},
            distinct_id: 'distinct-1',
        },
        events: [],
    }

    const baseEvent: LLMTraceEvent = {
        id: 'event-1',
        event: '$ai_span',
        properties: {
            $ai_span_name: 'Root span',
        },
        createdAt: '2025-01-01T00:00:00Z',
    }

    it.each([
        [{ ...baseTrace, inputState: 'hello' }, true],
        [{ ...baseTrace, outputState: { ok: true } }, true],
        [{ ...baseTrace }, false],
    ])('hasTraceContent returns %p for trace payload', (trace, expected) => {
        expect(hasTraceContent(trace)).toBe(expected)
    })

    it('finds nested nodes by event id', () => {
        const tree: EnrichedTraceTreeNode[] = [
            {
                event: baseEvent,
                displayTotalCost: 0,
                displayLatency: 0,
                displayUsage: null,
                children: [
                    {
                        event: {
                            ...baseEvent,
                            id: 'event-2',
                            properties: { $ai_span_name: 'Child span' },
                        },
                        displayTotalCost: 0,
                        displayLatency: 0,
                        displayUsage: null,
                    },
                ],
            },
        ]

        expect(findNodeByEventId(tree, 'event-2')?.event.id).toBe('event-2')
        expect(findNodeByEventId(tree, 'missing')).toBeNull()
    })
})
