import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { dataColorVars } from 'lib/colors'
import { dayjs } from 'lib/dayjs'
import { humanFriendlyDetailedTime } from 'lib/utils'

import { AggregatedSpanRow, SpanTreeNode } from '~/queries/schema/schema-general'
import { PropertyGroupFilter } from '~/types'

import type { tracingDataLogicType } from './tracingDataLogicType'
import { tracingFiltersLogic } from './tracingFiltersLogic'
import type { Span } from './types'

export interface SparklineRow {
    time: string
    service: string
    count: number
}

export interface TracingSparklineData {
    data: { name: string; values: number[]; color: string }[]
    dates: string[]
    labels: string[]
}

export interface VisibleRowRange {
    startIndex: number
    stopIndex: number
}

export interface VisibleSpanTimeRange {
    date_from: string
    date_to: string
}

const DEFAULT_PAGE_SIZE = 100
export const PREFETCH_SPANS = 20
const NEW_QUERY_STARTED_ERROR_MESSAGE = 'new query started' as const

function isUserInitiatedError(error: unknown): boolean {
    const errorStr = String(error).toLowerCase()
    return error === NEW_QUERY_STARTED_ERROR_MESSAGE || errorStr.includes('abort')
}

function captureTracingResults(count: number, queryType: 'spans' | 'aggregation'): void {
    if (count === 0) {
        posthog.capture('tracing no results returned', { query_type: queryType })
    } else {
        posthog.capture('tracing results returned', { count, query_type: queryType })
    }
}

export const tracingDataLogic = kea<tracingDataLogicType>([
    path(['products', 'tracing', 'frontend', 'tracingDataLogic']),

    connect(() => ({
        values: [tracingFiltersLogic(), ['filters', 'utcDateRange', 'currentWindowMs', 'previousWindowMs']],
    })),

    actions({
        runQuery: true,
        fetchNextPage: true,
        clearSpans: true,
        cancelInProgressSpans: (controller: AbortController | null) => ({ controller }),
        cancelInProgressSparkline: (controller: AbortController | null) => ({ controller }),
        cancelInProgressAggregation: (controller: AbortController | null) => ({ controller }),
        cancelInProgressSpanTree: (controller: AbortController | null) => ({ controller }),
        setSpansAbortController: (controller: AbortController | null) => ({ controller }),
        setSparklineAbortController: (controller: AbortController | null) => ({ controller }),
        setAggregationAbortController: (controller: AbortController | null) => ({ controller }),
        setSpanTreeAbortController: (controller: AbortController | null) => ({ controller }),
        setHasMoreToLoad: (hasMore: boolean) => ({ hasMore }),
        setNextCursor: (cursor: string | null) => ({ cursor }),
        setVisibleRowRange: (startIndex: number, stopIndex: number) => ({ startIndex, stopIndex }),
        /**
         * Snapshot the resolved time windows used for the last aggregation fetch.
         * The drill-down flame query reads this snapshot instead of recomputing from
         * the (potentially shifted) `-1h`-style relative date range, so its numbers
         * line up with the row the user clicked.
         */
        setLastAggregationWindow: (window: {
            currentStartMs: number
            currentEndMs: number
            previousStartMs: number
            previousEndMs: number
        }) => ({ window }),
    }),

    reducers({
        spansAbortController: [
            null as AbortController | null,
            { setSpansAbortController: (_, { controller }) => controller },
        ],
        sparklineAbortController: [
            null as AbortController | null,
            { setSparklineAbortController: (_, { controller }) => controller },
        ],
        aggregationAbortController: [
            null as AbortController | null,
            { setAggregationAbortController: (_, { controller }) => controller },
        ],
        spanTreeAbortController: [
            null as AbortController | null,
            { setSpanTreeAbortController: (_, { controller }) => controller },
        ],
        lastAggregationWindow: [
            null as null | {
                currentStartMs: number
                currentEndMs: number
                previousStartMs: number
                previousEndMs: number
            },
            { setLastAggregationWindow: (_, { window }) => window },
        ],
        hasRunQuery: [
            false as boolean,
            {
                fetchSpansSuccess: () => true,
                fetchSpansFailure: () => true,
            },
        ],
        spansLoading: [
            false as boolean,
            {
                fetchSpans: () => true,
                fetchSpansSuccess: () => false,
                fetchSpansFailure: () => false,
                fetchNextPage: () => true,
                fetchNextPageSuccess: () => false,
                fetchNextPageFailure: () => false,
            },
        ],
        sparklineLoading: [
            false as boolean,
            {
                fetchSparkline: () => true,
                fetchSparklineSuccess: () => false,
                fetchSparklineFailure: () => false,
            },
        ],
        aggregationLoading: [
            false as boolean,
            {
                fetchAggregation: () => true,
                fetchAggregationSuccess: () => false,
                fetchAggregationFailure: () => false,
            },
        ],
        spanTreeLoading: [
            false as boolean,
            {
                fetchSpanTree: () => true,
                fetchSpanTreeSuccess: () => false,
                fetchSpanTreeFailure: () => false,
            },
        ],
        hasMoreToLoad: [
            true as boolean,
            {
                setHasMoreToLoad: (_, { hasMore }) => hasMore,
                clearSpans: () => true,
            },
        ],
        nextCursor: [
            null as string | null,
            {
                setNextCursor: (_, { cursor }) => cursor,
                clearSpans: () => null,
            },
        ],
        visibleRowRange: [
            null as VisibleRowRange | null,
            {
                setVisibleRowRange: (_, { startIndex, stopIndex }) => ({ startIndex, stopIndex }),
                clearSpans: () => null,
            },
        ],
    }),

    loaders(({ values, actions }) => ({
        spans: [
            [] as Span[],
            {
                clearSpans: () => [],
                fetchSpans: async () => {
                    const controller = new AbortController()
                    actions.cancelInProgressSpans(controller)

                    const response = await api.tracing.listSpans(
                        {
                            dateRange: values.utcDateRange,
                            orderBy: values.filters.orderBy,
                            serviceNames:
                                values.filters.serviceNames.length > 0 ? values.filters.serviceNames : undefined,
                            filterGroup: values.filters.filterGroup as PropertyGroupFilter,
                            prefetchSpans: PREFETCH_SPANS,
                            limit: DEFAULT_PAGE_SIZE,
                        },
                        controller.signal
                    )

                    actions.setSpansAbortController(null)
                    actions.setHasMoreToLoad(!!response.hasMore)
                    actions.setNextCursor(response.nextCursor ?? null)
                    return response.results as Span[]
                },
                fetchNextPage: async () => {
                    if (!values.nextCursor) {
                        return values.spans
                    }

                    const controller = new AbortController()
                    actions.cancelInProgressSpans(controller)

                    const response = await api.tracing.listSpans(
                        {
                            dateRange: values.utcDateRange,
                            orderBy: values.filters.orderBy,
                            serviceNames:
                                values.filters.serviceNames.length > 0 ? values.filters.serviceNames : undefined,
                            filterGroup: values.filters.filterGroup as PropertyGroupFilter,
                            prefetchSpans: PREFETCH_SPANS,
                            limit: DEFAULT_PAGE_SIZE,
                            after: values.nextCursor,
                        },
                        controller.signal
                    )

                    actions.setSpansAbortController(null)
                    actions.setHasMoreToLoad(!!response.hasMore)
                    actions.setNextCursor(response.nextCursor ?? null)
                    return [...values.spans, ...(response.results as Span[])]
                },
            },
        ],
        traceSpans: [
            [] as Span[],
            {
                loadTraceSpans: async (traceId: string): Promise<Span[]> => {
                    const response = await api.tracing.getTrace(traceId, {
                        dateRange: {
                            date_from: values.utcDateRange.date_from ?? '-24h',
                            date_to: values.utcDateRange.date_to ?? undefined,
                        },
                        serviceNames: values.filters.serviceNames.length > 0 ? values.filters.serviceNames : undefined,
                        filterGroup: values.filters.filterGroup as PropertyGroupFilter,
                    })
                    return response.results as Span[]
                },
            },
        ],
        spanTree: [
            {
                spanName: null as string | null,
                current: [] as SpanTreeNode[],
                previous: null as SpanTreeNode[] | null,
            },
            {
                fetchSpanTree: async (params: { spanName: string; serviceName: string }) => {
                    // Abort any in-flight tree fetch so rapid row-clicks can't deliver a stale
                    // response that overwrites the newer one — matches the pattern used by
                    // fetchSpans / fetchSparkline / fetchAggregation.
                    const controller = new AbortController()
                    actions.cancelInProgressSpanTree(controller)

                    // Use the snapshotted window from the last aggregation fetch when available
                    // so the drill-down numbers align with the row the user clicked. Fall back
                    // to the live computed window only on a cold start (e.g. deep link before
                    // any aggregation has run).
                    const snapshot = values.lastAggregationWindow
                    const currentStartMs = snapshot?.currentStartMs ?? values.currentWindowMs.startMs
                    const currentEndMs = snapshot?.currentEndMs ?? values.currentWindowMs.endMs
                    const previousStartMs = snapshot?.previousStartMs ?? values.previousWindowMs.startMs

                    const response = await api.tracing.tree(
                        {
                            spanName: params.spanName,
                            serviceName: params.serviceName,
                            dateRange: {
                                date_from: new Date(currentStartMs).toISOString(),
                                date_to: new Date(currentEndMs).toISOString(),
                            },
                            serviceNames:
                                values.filters.serviceNames.length > 0 ? values.filters.serviceNames : undefined,
                            filterGroup: values.filters.filterGroup as PropertyGroupFilter,
                            compareFilter: {
                                compare: values.filters.compareMode,
                                compare_to: new Date(previousStartMs).toISOString(),
                            },
                        },
                        controller.signal
                    )

                    actions.setSpanTreeAbortController(null)
                    return {
                        spanName: params.spanName,
                        current: response.results ?? [],
                        previous: response.compare ?? null,
                    }
                },
            },
        ],
        aggregation: [
            { current: [] as AggregatedSpanRow[], previous: null as AggregatedSpanRow[] | null },
            {
                fetchAggregation: async () => {
                    const controller = new AbortController()
                    actions.cancelInProgressAggregation(controller)

                    // Snapshot the resolved windows so the drill-down flame query uses the
                    // same absolute timestamps as this aggregation, even if the user's
                    // relative `-1h` range has since shifted forward in time. Dispatched
                    // BEFORE the await so a concurrent `fetchSpanTree` (e.g. fired from the
                    // same `setOverlayWindows` listener) reads the new window, not the old.
                    const window = {
                        currentStartMs: values.currentWindowMs.startMs,
                        currentEndMs: values.currentWindowMs.endMs,
                        previousStartMs: values.previousWindowMs.startMs,
                        previousEndMs: values.previousWindowMs.endMs,
                    }
                    actions.setLastAggregationWindow(window)

                    const response = await api.tracing.aggregate(
                        {
                            dateRange: {
                                date_from: new Date(window.currentStartMs).toISOString(),
                                date_to: new Date(window.currentEndMs).toISOString(),
                            },
                            serviceNames:
                                values.filters.serviceNames.length > 0 ? values.filters.serviceNames : undefined,
                            filterGroup: values.filters.filterGroup as PropertyGroupFilter,
                            compareFilter: {
                                compare: values.filters.compareMode,
                                compare_to: new Date(window.previousStartMs).toISOString(),
                            },
                        },
                        controller.signal
                    )

                    actions.setAggregationAbortController(null)
                    return {
                        current: response.results ?? [],
                        previous: response.compare ?? null,
                    }
                },
            },
        ],
        rawSparklineData: [
            [] as SparklineRow[],
            {
                fetchSparkline: async () => {
                    const controller = new AbortController()
                    actions.cancelInProgressSparkline(controller)

                    const response = await api.tracing.sparkline(
                        {
                            dateRange: values.utcDateRange,
                            serviceNames:
                                values.filters.serviceNames.length > 0 ? values.filters.serviceNames : undefined,
                            filterGroup: values.filters.filterGroup as PropertyGroupFilter,
                        },
                        controller.signal
                    )

                    actions.setSparklineAbortController(null)
                    return response.results
                },
            },
        ],
    })),

    selectors({
        sparklineData: [
            (s) => [s.rawSparklineData],
            (rows: SparklineRow[]): TracingSparklineData => {
                if (!rows.length) {
                    return { data: [], dates: [], labels: [] }
                }

                let lastTime = ''
                let i = -1
                const labels: string[] = []
                const dates: string[] = []
                const accumulated = rows.reduce(
                    (accumulator, currentItem) => {
                        if (currentItem.time !== lastTime) {
                            labels.push(
                                humanFriendlyDetailedTime(currentItem.time, 'YYYY-MM-DD', 'HH:mm:ss', {
                                    timestampStyle: 'absolute',
                                })
                            )
                            dates.push(currentItem.time)
                            lastTime = currentItem.time
                            i++
                        }
                        const key = currentItem.service
                        if (!key) {
                            return accumulator
                        }
                        if (!accumulator[key]) {
                            accumulator[key] = []
                        }
                        while (accumulator[key].length <= i) {
                            accumulator[key].push(0)
                        }
                        accumulator[key][i] += currentItem.count
                        return accumulator
                    },
                    {} as Record<string, number[]>
                )

                const data = Object.entries(accumulated)
                    .sort(([a], [b]) => a.localeCompare(b))
                    .map(([name, values], index) => ({
                        name,
                        values: values as number[],
                        color: dataColorVars[index % dataColorVars.length],
                    }))
                    .filter((series) => series.values.reduce((a, b) => a + b) > 0)

                return { data, labels, dates }
            },
        ],
        totalSpansMatchingFilters: [
            (s) => [s.rawSparklineData],
            (rows: SparklineRow[]): number => rows.reduce((sum, item) => sum + item.count, 0),
        ],
        rootSpans: [
            (s) => [s.spans],
            (spans: Span[]): Span[] => {
                return spans.filter((s) => s.is_root_span)
            },
        ],

        // Date range covered by the currently-visible (scrolled-into-view) rows. Mirrors the
        // logs viewer so the sparkline can highlight the window the list is showing. Values are
        // always ordered date_from <= date_to regardless of the list's sort order.
        visibleRowDateRange: [
            (s) => [s.visibleRowRange, s.rootSpans],
            (visibleRowRange: VisibleRowRange | null, rootSpans: Span[]): VisibleSpanTimeRange | null => {
                if (!visibleRowRange || rootSpans.length === 0) {
                    return null
                }
                const startIndex = Math.max(0, Math.min(visibleRowRange.startIndex, rootSpans.length - 1))
                const stopIndex = Math.max(0, Math.min(visibleRowRange.stopIndex, rootSpans.length - 1))
                const a = rootSpans[startIndex]?.timestamp
                const b = rootSpans[stopIndex]?.timestamp
                if (!a || !b) {
                    return null
                }
                const ta = dayjs(a)
                const tb = dayjs(b)
                const [earlier, later] = ta.isBefore(tb) ? [ta, tb] : [tb, ta]
                return {
                    date_from: earlier.toISOString(),
                    date_to: later.toISOString(),
                }
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        runQuery: () => {
            actions.clearSpans()
            actions.fetchSparkline()
            if (values.filters.compareMode) {
                actions.fetchAggregation()
            } else {
                actions.fetchSpans()
            }
        },
        cancelInProgressSpans: ({ controller }) => {
            if (values.spansAbortController !== null) {
                values.spansAbortController.abort(NEW_QUERY_STARTED_ERROR_MESSAGE)
            }
            actions.setSpansAbortController(controller)
        },
        cancelInProgressSparkline: ({ controller }) => {
            if (values.sparklineAbortController !== null) {
                values.sparklineAbortController.abort(NEW_QUERY_STARTED_ERROR_MESSAGE)
            }
            actions.setSparklineAbortController(controller)
        },
        cancelInProgressAggregation: ({ controller }) => {
            if (values.aggregationAbortController !== null) {
                values.aggregationAbortController.abort(NEW_QUERY_STARTED_ERROR_MESSAGE)
            }
            actions.setAggregationAbortController(controller)
        },
        cancelInProgressSpanTree: ({ controller }) => {
            if (values.spanTreeAbortController !== null) {
                values.spanTreeAbortController.abort(NEW_QUERY_STARTED_ERROR_MESSAGE)
            }
            actions.setSpanTreeAbortController(controller)
        },
        fetchSpansSuccess: () => {
            captureTracingResults(values.rootSpans.length, 'spans')
        },
        fetchAggregationSuccess: ({ aggregation }) => {
            captureTracingResults(aggregation.current.length, 'aggregation')
        },
        fetchSpansFailure: ({ error }) => {
            if (!isUserInitiatedError(error)) {
                lemonToast.error(`Failed to load traces: ${error}`)
                posthog.capture('tracing query failed', { query_type: 'spans', error_message: String(error) })
            }
        },
        fetchSparklineFailure: ({ error }) => {
            if (!isUserInitiatedError(error)) {
                // Sparkline failures are non-critical, don't show toast
            }
        },
        fetchAggregationFailure: ({ error }) => {
            if (!isUserInitiatedError(error)) {
                lemonToast.error(`Failed to load span aggregation: ${error}`)
            }
        },
        fetchSpanTreeFailure: ({ error }) => {
            if (!isUserInitiatedError(error)) {
                lemonToast.error(`Failed to load call tree: ${error}`)
            }
        },
    })),

    events(({ values }) => ({
        beforeUnmount: () => {
            if (values.spansAbortController) {
                values.spansAbortController.abort('unmounting component')
            }
            if (values.sparklineAbortController) {
                values.sparklineAbortController.abort('unmounting component')
            }
            if (values.spanTreeAbortController) {
                values.spanTreeAbortController.abort('unmounting component')
            }
            if (values.aggregationAbortController) {
                values.aggregationAbortController.abort('unmounting component')
            }
        },
    })),
])
