import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { AggregatedSpanRow } from '~/queries/schema/schema-general'
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
    p99_duration_nano: 1000,
    p999_duration_nano: 1000,
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
    afterEach(resumeKeaLoadersErrors)
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
            // listRows = [root-1, root-2] in traces mode; index 1 is root-2, never the child at 05:00.
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

    describe('view mode', () => {
        const withChildSpans: Span[] = [
            createMockSpan('root-1', '2024-01-01T00:00:00Z'),
            { ...createMockSpan('child-1', '2024-01-01T00:00:01Z'), parent_span_id: 'root-1', is_root_span: false },
            createMockSpan('root-2', '2024-01-01T01:00:00Z'),
        ]

        it('lists only root spans in traces mode (default)', () => {
            logic = mountWithSpans(withChildSpans)
            expect(logic.values.filters.viewMode).toBe('traces')
            expect(logic.values.listRows.map((s) => s.uuid)).toEqual(['root-1', 'root-2'])
        })

        it('lists every span (root and child) in spans mode', () => {
            logic = mountWithSpans(withChildSpans)
            tracingFiltersLogic().actions.setViewMode('spans')
            expect(logic.values.listRows.map((s) => s.uuid)).toEqual(['root-1', 'child-1', 'root-2'])
        })

        it('requests flat spans from the API when in spans mode', async () => {
            const listSpansSpy = jest.spyOn(api.tracing, 'listSpans').mockResolvedValue({ results: [], hasMore: false })
            logic = mountWithSpans([])
            tracingFiltersLogic().actions.setViewMode('spans')
            await logic.asyncActions.fetchSpans()
            expect(listSpansSpy).toHaveBeenCalledWith(expect.objectContaining({ flatSpans: true }), expect.anything())
            listSpansSpy.mockRestore()
        })

        it('requests grouped traces from the API in traces mode', async () => {
            const listSpansSpy = jest.spyOn(api.tracing, 'listSpans').mockResolvedValue({ results: [], hasMore: false })
            logic = mountWithSpans([])
            await logic.asyncActions.fetchSpans()
            expect(listSpansSpy).toHaveBeenCalledWith(expect.objectContaining({ flatSpans: false }), expect.anything())
            listSpansSpy.mockRestore()
        })

        it('totalMatchingFilters reports trace count in traces mode and span count in spans mode', () => {
            logic = mountWithSpans([])
            logic.actions.fetchMatchingCountsSuccess({ count: 5000, traceCount: 100 })
            expect(logic.values.totalMatchingFilters).toBe(100)
            tracingFiltersLogic().actions.setViewMode('spans')
            expect(logic.values.totalMatchingFilters).toBe(5000)
        })

        it('sparkline counts root spans in traces mode and all spans in spans mode', async () => {
            const sparklineSpy = jest.spyOn(api.tracing, 'sparkline').mockResolvedValue({ results: [] })
            logic = mountWithSpans([])
            await logic.asyncActions.fetchSparkline()
            expect(sparklineSpy).toHaveBeenCalledWith(expect.objectContaining({ rootSpans: true }), expect.anything())
            tracingFiltersLogic().actions.setViewMode('spans')
            await logic.asyncActions.fetchSparkline()
            expect(sparklineSpy).toHaveBeenLastCalledWith(
                expect.objectContaining({ rootSpans: false }),
                expect.anything()
            )
            sparklineSpy.mockRestore()
        })
    })

    describe('matching counts', () => {
        it('does not re-fetch the count when only the view mode changes', async () => {
            const countSpy = jest.spyOn(api.tracing, 'count').mockResolvedValue({ count: 10, traceCount: 3 })
            logic = mountWithSpans([])
            await logic.asyncActions.fetchMatchingCounts()
            tracingFiltersLogic().actions.setViewMode('spans')
            await logic.asyncActions.fetchMatchingCounts()
            // The count is view-mode-independent, so the second run reuses the cached result.
            expect(countSpy).toHaveBeenCalledTimes(1)
            countSpy.mockRestore()
        })

        it('re-fetches the count when the data scope changes', async () => {
            const countSpy = jest.spyOn(api.tracing, 'count').mockResolvedValue({ count: 10, traceCount: 3 })
            logic = mountWithSpans([])
            await logic.asyncActions.fetchMatchingCounts()
            tracingFiltersLogic().actions.setServiceNames(['api'])
            await logic.asyncActions.fetchMatchingCounts()
            expect(countSpy).toHaveBeenCalledTimes(2)
            countSpy.mockRestore()
        })

        it('toasts on a real count failure', async () => {
            silenceKeaLoadersErrors()
            const toastSpy = jest.spyOn(lemonToast, 'error').mockReturnValue(undefined as any)
            jest.spyOn(api.tracing, 'count').mockRejectedValue(new Error('boom'))
            logic = mountWithSpans([])
            await logic.asyncActions.fetchMatchingCounts().catch(() => {})
            expect(toastSpy).toHaveBeenCalled()
            toastSpy.mockRestore()
        })
    })

    describe('sparkline', () => {
        it('re-fetches the sparkline when the view mode changes', async () => {
            const sparklineSpy = jest.spyOn(api.tracing, 'sparkline').mockResolvedValue({ results: [] })
            logic = mountWithSpans([])
            await logic.asyncActions.fetchSparkline()
            tracingFiltersLogic().actions.setViewMode('spans')
            await logic.asyncActions.fetchSparkline()
            // The sparkline counts root spans in 'traces' mode and all spans in 'spans' mode, so a
            // view-mode toggle changes its scope and must re-fetch.
            expect(sparklineSpy).toHaveBeenCalledTimes(2)
            sparklineSpy.mockRestore()
        })

        it('re-fetches the sparkline when the data scope changes', async () => {
            const sparklineSpy = jest.spyOn(api.tracing, 'sparkline').mockResolvedValue({ results: [] })
            logic = mountWithSpans([])
            await logic.asyncActions.fetchSparkline()
            tracingFiltersLogic().actions.setServiceNames(['api'])
            await logic.asyncActions.fetchSparkline()
            expect(sparklineSpy).toHaveBeenCalledTimes(2)
            sparklineSpy.mockRestore()
        })
    })
})
