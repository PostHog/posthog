import posthog from 'posthog-js'

import { AggregatedSpanRow } from '@posthog/query-frontend/schema/schema-general'

import { initKeaTests } from '~/test/init'

import { tracingDataLogic } from './tracingDataLogic'
import { tracingFiltersLogic } from './tracingFiltersLogic'
import type { Span } from './types'

const createMockAggregatedRow = (name: string): AggregatedSpanRow => ({
    service_name: 'svc',
    name,
    count: 1,
    total_duration_nano: 1000,
    avg_duration_nano: 1000,
    p50_duration_nano: 1000,
    p95_duration_nano: 1000,
    error_count: 0,
})

const createMockSpan = (uuid: string, timestamp: string): Span => ({
    uuid,
    trace_id: `trace-${uuid}`,
    span_id: uuid,
    parent_span_id: '',
    name: 'op',
    kind: 1,
    service_name: 'svc',
    status_code: 1,
    timestamp,
    end_time: timestamp,
    duration_nano: 1000,
    is_root_span: true,
    matched_filter: true,
    attributes: {},
    resource_attributes: {},
})

const mockSpans: Span[] = [
    createMockSpan('span-1', '2024-01-01T00:00:00Z'),
    createMockSpan('span-2', '2024-01-01T01:00:00Z'),
    createMockSpan('span-3', '2024-01-01T02:00:00Z'),
    createMockSpan('span-4', '2024-01-01T03:00:00Z'),
]

function mountWithSpans(spans: Span[] = mockSpans): ReturnType<typeof tracingDataLogic.build> {
    tracingFiltersLogic().mount()
    const logic = tracingDataLogic()
    logic.mount()
    if (spans.length > 0) {
        logic.actions.fetchSpansSuccess(spans)
    }
    return logic
}

describe('tracingDataLogic', () => {
    let logic: ReturnType<typeof tracingDataLogic.build>

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    describe('visible row range tracking', () => {
        beforeEach(() => {
            logic = mountWithSpans()
        })

        it('defaults to null', () => {
            expect(logic.values.visibleRowRange).toBeNull()
            expect(logic.values.visibleRowDateRange).toBeNull()
        })

        it('records the visible row index range', () => {
            logic.actions.setVisibleRowRange(1, 2)
            expect(logic.values.visibleRowRange).toEqual({ startIndex: 1, stopIndex: 2 })
        })

        it.each([
            {
                name: 'ascending spans',
                reverse: false,
                range: [1, 2] as const,
                expected: { date_from: '2024-01-01T01:00:00.000Z', date_to: '2024-01-01T02:00:00.000Z' },
            },
            {
                // "Latest first" — startIndex points at a later timestamp than stopIndex.
                name: 'descending spans',
                reverse: true,
                range: [0, 1] as const,
                expected: { date_from: '2024-01-01T02:00:00.000Z', date_to: '2024-01-01T03:00:00.000Z' },
            },
            {
                name: 'single-row range',
                reverse: false,
                range: [2, 2] as const,
                expected: { date_from: '2024-01-01T02:00:00.000Z', date_to: '2024-01-01T02:00:00.000Z' },
            },
        ])('derives a date range ordered earliest-first ($name)', ({ reverse, range, expected }) => {
            if (reverse) {
                logic.actions.fetchSpansSuccess([...mockSpans].reverse())
            }
            logic.actions.setVisibleRowRange(range[0], range[1])
            expect(logic.values.visibleRowDateRange).toEqual(expected)
        })

        it('clamps indices that fall outside the loaded spans', () => {
            logic.actions.setVisibleRowRange(0, 999)
            expect(logic.values.visibleRowDateRange).toEqual({
                date_from: '2024-01-01T00:00:00.000Z',
                date_to: '2024-01-01T03:00:00.000Z',
            })
        })

        it('ignores non-root spans when deriving the range', () => {
            const withChild = [
                createMockSpan('root-1', '2024-01-01T00:00:00Z'),
                { ...createMockSpan('child-1', '2024-01-01T05:00:00Z'), parent_span_id: 'root-1', is_root_span: false },
                createMockSpan('root-2', '2024-01-01T01:00:00Z'),
            ]
            logic.actions.fetchSpansSuccess(withChild)
            // rootSpans = [root-1, root-2]; index 1 is root-2, never the child at 05:00.
            logic.actions.setVisibleRowRange(0, 1)
            expect(logic.values.visibleRowDateRange).toEqual({
                date_from: '2024-01-01T00:00:00.000Z',
                date_to: '2024-01-01T01:00:00.000Z',
            })
        })

        it('clears when spans are reset', () => {
            logic.actions.setVisibleRowRange(0, 2)
            expect(logic.values.visibleRowDateRange).not.toBeNull()
            logic.actions.clearSpans()
            expect(logic.values.visibleRowRange).toBeNull()
            expect(logic.values.visibleRowDateRange).toBeNull()
        })
    })

    describe('results tracking', () => {
        let captureSpy: jest.SpyInstance

        beforeEach(() => {
            logic = mountWithSpans([])
            captureSpy = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined as any)
        })

        afterEach(() => {
            captureSpy.mockRestore()
        })

        it.each([
            {
                name: 'spans with a count',
                dispatch: (l: typeof logic) => l.actions.fetchSpansSuccess(mockSpans),
                event: 'tracing results returned',
                properties: { count: mockSpans.length, query_type: 'spans' },
            },
            {
                name: 'empty spans',
                dispatch: (l: typeof logic) => l.actions.fetchSpansSuccess([]),
                event: 'tracing no results returned',
                properties: { query_type: 'spans' },
            },
            {
                name: 'aggregation with a count',
                dispatch: (l: typeof logic) =>
                    l.actions.fetchAggregationSuccess({
                        current: [createMockAggregatedRow('op-1'), createMockAggregatedRow('op-2')],
                        previous: null,
                    }),
                event: 'tracing results returned',
                properties: { count: 2, query_type: 'aggregation' },
            },
            {
                name: 'empty aggregation',
                dispatch: (l: typeof logic) => l.actions.fetchAggregationSuccess({ current: [], previous: null }),
                event: 'tracing no results returned',
                properties: { query_type: 'aggregation' },
            },
        ])('captures the right event for $name', ({ dispatch, event, properties }) => {
            dispatch(logic)
            expect(captureSpy).toHaveBeenCalledWith(event, properties)
        })
    })
})
