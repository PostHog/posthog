import { LLMTraceEvent } from '~/queries/schema/schema-general'

import { TraceTreeNode, getEffectiveEventId, getInitialFocusEventId, restoreTree } from './llmAnalyticsTraceDataLogic'

describe('llmAnalyticsTraceDataLogic: restoreTree', () => {
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

    it('should treat orphaned events as roots when parent does not exist', () => {
        const events: LLMTraceEvent[] = [
            {
                id: '1',
                event: '$ai_span',
                properties: {
                    $ai_span_id: 'span-1',
                    $ai_parent_id: 'missing-parent',
                },
                createdAt: '2024-01-01T00:00:00Z',
            },
            {
                id: '2',
                event: '$ai_generation',
                properties: {
                    $ai_span_id: 'span-2',
                    $ai_parent_id: 'span-1',
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
                }),
                children: [
                    {
                        event: events[1],
                    },
                ],
            },
        ])
    })
})

describe('getInitialFocusEventId', () => {
    it('returns $ai_trace event id when present', () => {
        const events: LLMTraceEvent[] = [
            {
                id: 'span-1',
                event: '$ai_span',
                properties: {},
                createdAt: '2024-01-01T00:00:00Z',
            },
            {
                id: 'trace-event-1',
                event: '$ai_trace',
                properties: {},
                createdAt: '2024-01-01T00:00:00Z',
            },
        ]

        const tree: TraceTreeNode[] = [{ event: events[0] }]

        expect(getInitialFocusEventId(events, tree)).toBe('trace-event-1')
    })

    it('returns first $ai_generation event id when no $ai_trace event exists', () => {
        const events: LLMTraceEvent[] = [
            {
                id: 'span-1',
                event: '$ai_span',
                properties: {},
                createdAt: '2024-01-01T00:00:00Z',
            },
            {
                id: 'generation-1',
                event: '$ai_generation',
                properties: {},
                createdAt: '2024-01-01T00:00:00Z',
            },
        ]

        const tree: TraceTreeNode[] = [{ event: events[0] }, { event: events[1] }]

        expect(getInitialFocusEventId(events, tree)).toBe('generation-1')
    })

    it('returns first tree event id when no $ai_trace or $ai_generation events exist', () => {
        const events: LLMTraceEvent[] = [
            {
                id: 'span-1',
                event: '$ai_span',
                properties: {},
                createdAt: '2024-01-01T00:00:00Z',
            },
            {
                id: 'span-2',
                event: '$ai_span',
                properties: {},
                createdAt: '2024-01-01T00:00:00Z',
            },
        ]

        const tree: TraceTreeNode[] = [{ event: events[0] }, { event: events[1] }]

        expect(getInitialFocusEventId(events, tree)).toBe('span-1')
    })

    it('returns null when no events exist', () => {
        expect(getInitialFocusEventId([], [])).toBeNull()
    })

    it('prioritizes $ai_trace over $ai_generation and tree order', () => {
        const generationEvent: LLMTraceEvent = {
            id: 'generation-1',
            event: '$ai_generation',
            properties: {},
            createdAt: '2024-01-01T00:00:00Z',
        }

        const traceEvent: LLMTraceEvent = {
            id: 'trace-event-1',
            event: '$ai_trace',
            properties: {},
            createdAt: '2024-01-01T00:00:00Z',
        }

        const events: LLMTraceEvent[] = [generationEvent, traceEvent]

        // Tree has generation first, but $ai_trace should still be selected
        const tree: TraceTreeNode[] = [{ event: generationEvent }]

        expect(getInitialFocusEventId(events, tree)).toBe('trace-event-1')
    })

    it('skips $ai_generation events not in filtered tree', () => {
        const spanEvent: LLMTraceEvent = {
            id: 'span-1',
            event: '$ai_span',
            properties: {},
            createdAt: '2024-01-01T00:00:00Z',
        }

        const generationEvent: LLMTraceEvent = {
            id: 'generation-1',
            event: '$ai_generation',
            properties: {},
            createdAt: '2024-01-01T00:00:00Z',
        }

        const events: LLMTraceEvent[] = [spanEvent, generationEvent]

        // Tree only has span (e.g., generation was filtered out by search)
        const tree: TraceTreeNode[] = [{ event: spanEvent }]

        // Should return first tree event since generation is not in tree
        expect(getInitialFocusEventId(events, tree)).toBe('span-1')
    })
})

describe('getEffectiveEventId', () => {
    it('returns eventId when user has selected an event', () => {
        expect(getEffectiveEventId('selected-event-id', 'initial-focus-id')).toBe('selected-event-id')
    })

    it('returns initialFocusEventId when eventId is null', () => {
        expect(getEffectiveEventId(null, 'initial-focus-id')).toBe('initial-focus-id')
    })

    it('returns null when both eventId and initialFocusEventId are null', () => {
        expect(getEffectiveEventId(null, null)).toBeNull()
    })
})
