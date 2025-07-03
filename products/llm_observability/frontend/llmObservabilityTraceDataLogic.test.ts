import { LLMTraceEvent } from '~/queries/schema/schema-general'

import { restoreTree } from './llmObservabilityTraceDataLogic'

describe('llmObservabilityTraceDataLogic: restoreTree', () => {
    it('should group a basic trace into a tree', () => {
        const events: LLMTraceEvent[] = [
            {
                id: '1',
                event: '$ai_span',
                properties: {
                    $ai_parent_id: 'trace',
                },
                createdAt: '2024-01-01T00:00:00Z',
            },
            {
                id: '2',
                event: '$ai_generation',
                properties: {
                    $ai_parent_id: 'trace',
                },
                createdAt: '2024-01-01T00:00:00Z',
            },
        ]

        const tree = restoreTree(events, 'trace')
        expect(tree).toEqual([
            {
                event: events[0],
            },
            {
                event: events[1],
            },
        ])
    })

    it('should build a nested tree', () => {
        const events: LLMTraceEvent[] = [
            {
                id: '1',
                event: '$ai_span',
                properties: {
                    $ai_parent_id: 'trace',
                },
                createdAt: '2024-01-01T00:00:00Z',
            },
            {
                id: '2',
                event: '$ai_span',
                properties: {
                    $ai_parent_id: '1',
                },
                createdAt: '2024-01-01T00:00:00Z',
            },
            {
                id: '3',
                event: '$ai_span',
                properties: {
                    $ai_parent_id: '2',
                },
                createdAt: '2024-01-01T00:00:00Z',
            },
        ]

        const tree = restoreTree(events, 'trace')
        expect(tree).toEqual([
            {
                event: events[0],
                aggregation: expect.objectContaining({
                    totalCost: 0,
                    totalLatency: 0,
                    inputTokens: 0,
                    outputTokens: 0,
                }),
                children: [
                    {
                        event: events[1],
                        aggregation: expect.objectContaining({
                            totalCost: 0,
                            totalLatency: 0,
                            inputTokens: 0,
                            outputTokens: 0,
                        }),
                        children: [
                            {
                                event: events[2],
                                children: undefined,
                            },
                        ],
                    },
                ],
            },
        ])
    })

    it('should filter out feedback and metric events', () => {
        const events: LLMTraceEvent[] = [
            {
                id: '1',
                event: '$ai_span',
                properties: {
                    $ai_parent_id: 'trace',
                },
                createdAt: '2024-01-01T00:00:00Z',
            },
            {
                id: '2',
                event: '$ai_feedback',
                properties: {
                    $ai_parent_id: 'trace',
                },
                createdAt: '2024-01-01T00:00:00Z',
            },
            {
                id: '3',
                event: '$ai_metric',
                properties: {
                    $ai_parent_id: 'trace',
                },
                createdAt: '2024-01-01T00:00:00Z',
            },
        ]

        const tree = restoreTree(events, 'trace')
        expect(tree).toEqual([
            {
                event: events[0],
            },
        ])
    })

    it('should group legacy events without a $ai_parent_id', () => {
        const events: LLMTraceEvent[] = [
            {
                id: '1',
                event: '$ai_span',
                properties: {
                    $ai_trace_id: 'trace',
                },
                createdAt: '2024-01-01T00:00:00Z',
            },
            {
                id: '2',
                event: '$ai_span',
                properties: {
                    $ai_trace_id: 'trace',
                },
                createdAt: '2024-01-01T00:00:00Z',
            },
        ]

        const tree = restoreTree(events, 'trace')
        expect(tree).toEqual([
            {
                event: events[0],
                children: undefined,
            },
            {
                event: events[1],
                children: undefined,
            },
        ])
    })
})
