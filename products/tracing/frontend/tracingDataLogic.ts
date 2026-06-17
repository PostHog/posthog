import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { dataColorVars } from 'lib/colors'
import { dayjs } from 'lib/dayjs'
import { humanFriendlyDetailedTime } from 'lib/utils/datetime'

import { AggregatedSpanRow, SpanTreeNode } from '~/queries/schema/schema-general'
import { PropertyGroupFilter } from '~/types'

import {
    type DurationHistogramRow,
    pivotDurationHistogram,
    type TracingDurationHistogramData,
    type VisibleDurationRange,
    visibleDurationRange,
} from './durationBuckets'
import { traceLookupDateRange } from './traceLinks'
import type { tracingDataLogicType } from './tracingDataLogicType'
import { type TracingFilters, type TracingOrderBy, tracingFiltersLogic } from './tracingFiltersLogic'
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

// A ts hint (from a shared/cold link) bounds the lookup tightly around the trace instead of the
// scene's current date range — the table is time-keyed, so this is what keeps an id lookup from
// scanning the whole window. Guard validity: a hand-edited/corrupted ts would otherwise make dayjs
// throw on toISOString().
function resolveTraceLookupRange(
    ts: string | null | undefined,
    utcDateRange: { date_from?: string | null; date_to?: string | null }
): { date_from?: string | null; date_to?: string | null } {
    if (ts && dayjs(ts).isValid()) {
        return traceLookupDateRange(ts)
    }
    return {
        date_from: utcDateRange.date_from ?? '-24h',
        date_to: utcDateRange.date_to ?? undefined,
    }
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
        values: [tracingFiltersLogic(), ['filters', 'orderBy', 'utcDateRange', 'currentWindowMs', 'previousWindowMs']],
    })),

    actions({
        runQuery: true,
        fetchNextPage: true,
        loadMoreTraceSpans: true,
        setTracePagination: (hasMore: boolean, nextOffset: number | null) => ({ hasMore, nextOffset }),
        clearSpans: true,
        cancelInProgressSpans: (controller: AbortController | null) => ({ controller }),
        cancelInProgressSparkline: (controller: AbortController | null) => ({ controller }),
        cancelInProgressDurationHistogram: (controller: AbortController | null) => ({ controller }),
        cancelInProgressAggregation: (controller: AbortController | null) => ({ controller }),
        cancelInProgressSpanTree: (controller: AbortController | null) => ({ controller }),
        setSpansAbortController: (controller: AbortController | null) => ({ controller }),
        setSparklineAbortController: (controller: AbortController | null) => ({ controller }),
        setDurationHistogramAbortController: (controller: AbortController | null) => ({ controller }),
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
        durationHistogramAbortController: [
            null as AbortController | null,
            { setDurationHistogramAbortController: (_, { controller }) => controller },
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
        durationHistogramLoading: [
            false as boolean,
            {
                fetchDurationHistogram: () => true,
                fetchDurationHistogramSuccess: () => false,
                fetchDurationHistogramFailure: () => false,
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
        // Whether the open trace has more spans than the loaded pages (drives the waterfall's
        // infinite scroll). Reset on every fresh trace open so a small trace can't inherit a
        // previous trace's "load more" affordance.
        traceSpansHasMore: [
            false as boolean,
            {
                setTracePagination: (_, { hasMore }) => hasMore,
                loadTraceSpans: () => false,
            },
        ],
        // Offset to request for the next waterfall page (count of spans already loaded for the trace).
        traceSpansNextOffset: [
            0 as number,
            {
                setTracePagination: (_, { nextOffset }) => nextOffset ?? 0,
                loadTraceSpans: () => 0,
            },
        ],
        // The trace + ts the loaded spans belong to, so `loadMoreTraceSpans` can refetch the next
        // page with the same lookup window without re-deriving it from a since-shifted date range.
        traceLoadContext: [
            null as { traceId: string; ts?: string | null } | null,
            {
                loadTraceSpans: (_, { traceId, ts }) => ({ traceId, ts }),
                clearSpans: () => null,
            },
        ],
        // Separate from the loader's own `traceSpansLoading` so paging in more spans shows a small
        // bottom spinner rather than the drawer's full-trace overlay (see `isLoadingFullTrace`).
        traceSpansLoadingMore: [
            false as boolean,
            {
                loadMoreTraceSpans: () => true,
                loadMoreTraceSpansSuccess: () => false,
                loadMoreTraceSpansFailure: () => false,
                // A fresh trace fetch must show the full-trace overlay even if a stale load-more is
                // still in flight.
                loadTraceSpans: () => false,
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
                            orderDirection: values.filters.orderDirection,
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
                    if (!values.hasMoreToLoad) {
                        return values.spans
                    }

                    const controller = new AbortController()
                    actions.cancelInProgressSpans(controller)

                    // Duration ordering paginates by offset (it has no keyset cursor); timestamp
                    // ordering uses the `after` cursor. Offset is the count of traces already shown.
                    const pagination =
                        values.filters.orderBy === 'duration'
                            ? { offset: values.rootSpans.length }
                            : { after: values.nextCursor ?? undefined }

                    const response = await api.tracing.listSpans(
                        {
                            dateRange: values.utcDateRange,
                            orderBy: values.filters.orderBy,
                            orderDirection: values.filters.orderDirection,
                            serviceNames:
                                values.filters.serviceNames.length > 0 ? values.filters.serviceNames : undefined,
                            filterGroup: values.filters.filterGroup as PropertyGroupFilter,
                            prefetchSpans: PREFETCH_SPANS,
                            limit: DEFAULT_PAGE_SIZE,
                            ...pagination,
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
                loadTraceSpans: async ({ traceId, ts }: { traceId: string; ts?: string | null }): Promise<Span[]> => {
                    const response = await api.tracing.getTrace(traceId, {
                        dateRange: resolveTraceLookupRange(ts, values.utcDateRange),
                        serviceNames: values.filters.serviceNames.length > 0 ? values.filters.serviceNames : undefined,
                        filterGroup: values.filters.filterGroup as PropertyGroupFilter,
                    })
                    actions.setTracePagination(!!response.hasMore, response.nextOffset ?? null)
                    return response.results as Span[]
                },
                // Infinite scroll: page in the next batch of the open trace's spans (earliest first)
                // and append. Guarded so a trailing scroll event after the last page is a no-op.
                loadMoreTraceSpans: async (): Promise<Span[]> => {
                    if (!values.traceSpansHasMore || !values.traceLoadContext) {
                        return values.traceSpans
                    }
                    const { traceId, ts } = values.traceLoadContext
                    const response = await api.tracing.getTrace(traceId, {
                        dateRange: resolveTraceLookupRange(ts, values.utcDateRange),
                        serviceNames: values.filters.serviceNames.length > 0 ? values.filters.serviceNames : undefined,
                        filterGroup: values.filters.filterGroup as PropertyGroupFilter,
                        offset: values.traceSpansNextOffset,
                    })
                    // Bail if a new trace was opened mid-fetch — appending this stale page to the new
                    // trace's spans would corrupt the waterfall.
                    if (values.traceLoadContext?.traceId !== traceId) {
                        return values.traceSpans
                    }
                    actions.setTracePagination(!!response.hasMore, response.nextOffset ?? null)
                    return [...values.traceSpans, ...(response.results as Span[])]
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
        rawDurationHistogram: [
            [] as DurationHistogramRow[],
            {
                fetchDurationHistogram: async () => {
                    const controller = new AbortController()
                    actions.cancelInProgressDurationHistogram(controller)

                    const response = await api.tracing.durationHistogram(
                        {
                            dateRange: values.utcDateRange,
                            serviceNames:
                                values.filters.serviceNames.length > 0 ? values.filters.serviceNames : undefined,
                            filterGroup: values.filters.filterGroup as PropertyGroupFilter,
                        },
                        controller.signal
                    )

                    actions.setDurationHistogramAbortController(null)
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
        durationHistogramData: [
            (s) => [s.rawDurationHistogram],
            (rows: DurationHistogramRow[]): TracingDurationHistogramData => pivotDurationHistogram(rows, dataColorVars),
        ],
        rootSpans: [
            (s) => [s.spans],
            (spans: Span[]): Span[] => {
                return spans.filter((s) => s.is_root_span)
            },
        ],
        // Memoized separately so visibleRowDurationRange (recomputed on every scroll tick) doesn't
        // re-allocate the durations array — this only changes when the loaded spans do.
        rootSpanDurations: [
            (s) => [s.rootSpans],
            (rootSpans: Span[]): number[] => rootSpans.map((span) => span.duration_nano),
        ],
        // Single owner of the "show the duration histogram?" rule — the fetch decision, the
        // highlight selector, and the scene's rendering all derive from this one place.
        // Compare mode replaces the span list with the aggregate table, so the histogram
        // (which mirrors the duration-sorted list) only applies outside it.
        isDurationMode: [
            (s) => [s.filters],
            (filters: TracingFilters): boolean => filters.orderBy === 'duration' && !filters.compareMode,
        ],

        // Duration range covered by the currently-visible rows — the duration-space sibling of
        // visibleRowDateRange below. When sorted by duration the visible rows are contiguous in
        // duration space, so the histogram can sweep a highlight across the distribution as the
        // user scrolls (the same interaction the time sparkline has under timestamp sort).
        visibleRowDurationRange: [
            (s) => [s.visibleRowRange, s.rootSpanDurations, s.isDurationMode],
            (
                visibleRowRange: VisibleRowRange | null,
                rootSpanDurations: number[],
                isDurationMode: boolean
            ): VisibleDurationRange | null => {
                if (!isDurationMode) {
                    return null
                }
                return visibleDurationRange(visibleRowRange, rootSpanDurations)
            },
        ],

        // Date range covered by the currently-visible (scrolled-into-view) rows, so the sparkline can
        // highlight the window the list is showing (mirrors the logs viewer). Only meaningful when the
        // list is time-ordered — under duration (or any non-timestamp) sort, consecutive rows aren't
        // contiguous in time, so the highlight would be meaningless. Suppress it then; the duration
        // histogram (visibleRowDurationRange above) covers the duration-sorted case.
        visibleRowDateRange: [
            (s) => [s.visibleRowRange, s.rootSpans, s.orderBy],
            (
                visibleRowRange: VisibleRowRange | null,
                rootSpans: Span[],
                orderBy: TracingOrderBy
            ): VisibleSpanTimeRange | null => {
                if (orderBy !== 'timestamp' || !visibleRowRange || rootSpans.length === 0) {
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
            // The time sparkline is always fetched — it also feeds totalSpansMatchingFilters, and
            // keeps the chart warm when the user flips back to timestamp sort. Duration sort
            // additionally fetches the histogram that replaces it visually.
            actions.fetchSparkline()
            if (values.isDurationMode) {
                actions.fetchDurationHistogram()
            }
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
        cancelInProgressDurationHistogram: ({ controller }) => {
            if (values.durationHistogramAbortController !== null) {
                values.durationHistogramAbortController.abort(NEW_QUERY_STARTED_ERROR_MESSAGE)
            }
            actions.setDurationHistogramAbortController(controller)
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
        loadMoreTraceSpansFailure: ({ error }) => {
            if (!isUserInitiatedError(error)) {
                lemonToast.error(`Failed to load more spans: ${error}`)
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
            if (values.durationHistogramAbortController) {
                values.durationHistogramAbortController.abort('unmounting component')
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
