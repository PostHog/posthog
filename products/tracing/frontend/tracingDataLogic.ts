import { actions, connect, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
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
import {
    type TracingFilters,
    type TracingOrderBy,
    TRACING_SCENE_VIEWER_ID,
    tracingFiltersLogic,
} from './tracingFiltersLogic'
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

export interface TracingDataLogicProps {
    id: string
}

export const tracingDataLogic = kea<tracingDataLogicType>([
    props({ id: TRACING_SCENE_VIEWER_ID } as TracingDataLogicProps),
    key((props) => props.id),
    path((key) => ['products', 'tracing', 'frontend', 'tracingDataLogic', key]),

    connect(({ id }: TracingDataLogicProps) => ({
        values: [
            tracingFiltersLogic({ id }),
            [
                'filters',
                'orderBy',
                'utcDateRange',
                'queryFilterGroup',
                'sparklineWindowMs',
                'currentWindowMs',
                'previousWindowMs',
                'compareActive',
                'timeComparison',
            ],
        ],
    })),

    actions({
        runQuery: true,
        fetchNextPage: true,
        loadMoreTraceSpans: true,
        setTracePagination: (hasMore: boolean, nextOffset: number | null) => ({ hasMore, nextOffset }),
        clearSpans: true,
        cancelInProgressSpans: (controller: AbortController | null) => ({ controller }),
        cancelInProgressSparkline: (controller: AbortController | null) => ({ controller }),
        cancelInProgressMatchingCounts: (controller: AbortController | null) => ({ controller }),
        cancelInProgressDurationHistogram: (controller: AbortController | null) => ({ controller }),
        cancelInProgressAggregation: (controller: AbortController | null) => ({ controller }),
        cancelInProgressSpanTree: (controller: AbortController | null) => ({ controller }),
        setSpansAbortController: (controller: AbortController | null) => ({ controller }),
        setSparklineAbortController: (controller: AbortController | null) => ({ controller }),
        setMatchingCountsAbortController: (controller: AbortController | null) => ({ controller }),
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
        matchingCountsAbortController: [
            null as AbortController | null,
            { setMatchingCountsAbortController: (_, { controller }) => controller },
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

    loaders(({ values, actions, cache }) => ({
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
                            filterGroup: values.queryFilterGroup as PropertyGroupFilter,
                            prefetchSpans: PREFETCH_SPANS,
                            flatSpans: values.filters.viewMode === 'spans',
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
                    // ordering uses the `after` cursor. Offset is the count of rows already shown.
                    const pagination =
                        values.filters.orderBy === 'duration'
                            ? { offset: values.listRows.length }
                            : { after: values.nextCursor ?? undefined }

                    const response = await api.tracing.listSpans(
                        {
                            dateRange: values.utcDateRange,
                            orderBy: values.filters.orderBy,
                            orderDirection: values.filters.orderDirection,
                            serviceNames:
                                values.filters.serviceNames.length > 0 ? values.filters.serviceNames : undefined,
                            filterGroup: values.queryFilterGroup as PropertyGroupFilter,
                            prefetchSpans: PREFETCH_SPANS,
                            flatSpans: values.filters.viewMode === 'spans',
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
                        filterGroup: values.queryFilterGroup as PropertyGroupFilter,
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
                        filterGroup: values.queryFilterGroup as PropertyGroupFilter,
                        offset: values.traceSpansNextOffset,
                    })
                    // Bail if a new trace was opened mid-fetch — appending this stale page to the new
                    // trace's spans would corrupt the waterfall.
                    if (values.traceLoadContext?.traceId !== traceId) {
                        return values.traceSpans
                    }
                    // Dedupe against what's already loaded: the waterfall keys its tree by span_id,
                    // so a page that overlaps prior pages wouldn't grow the rendered rows but would
                    // still balloon this array (and pin the infinite-scroll trigger at the bottom,
                    // spinning the CPU). If a page adds nothing new, stop paging.
                    const seen = new Set(values.traceSpans.map((s) => s.span_id))
                    const newSpans = (response.results as Span[]).filter((s) => !seen.has(s.span_id))
                    if (newSpans.length === 0) {
                        actions.setTracePagination(false, null)
                        return values.traceSpans
                    }
                    actions.setTracePagination(!!response.hasMore, response.nextOffset ?? null)
                    return [...values.traceSpans, ...newSpans]
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
                            filterGroup: values.queryFilterGroup as PropertyGroupFilter,
                            compareFilter: {
                                compare: values.timeComparison !== null,
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
                // `fullRange` (the Operations tab) ignores any active comparison: the aggregate
                // covers the whole selected range with no compare period, matching the rate
                // denominator the OperationsTable divides by.
                fetchAggregation: async (options?: { fullRange?: boolean } | null) => {
                    const controller = new AbortController()
                    actions.cancelInProgressAggregation(controller)

                    const fullRange = options?.fullRange ?? false
                    const currentWindow = fullRange ? values.sparklineWindowMs : values.currentWindowMs
                    const compare = !fullRange && values.timeComparison !== null

                    // Snapshot the resolved windows so the drill-down flame query uses the
                    // same absolute timestamps as this aggregation, even if the user's
                    // relative `-1h` range has since shifted forward in time. Dispatched
                    // BEFORE the await so a concurrent `fetchSpanTree` (e.g. fired from the
                    // same `updateComparisonWindows` listener) reads the new window, not the
                    // old. Full-range (Operations) fetches skip it — the flame drill-down
                    // only exists on the traces tab and must stay aligned with the compare
                    // aggregation, not the operations one.
                    const window = {
                        currentStartMs: currentWindow.startMs,
                        currentEndMs: currentWindow.endMs,
                        previousStartMs: values.previousWindowMs.startMs,
                        previousEndMs: values.previousWindowMs.endMs,
                    }
                    if (!fullRange) {
                        actions.setLastAggregationWindow(window)
                    }

                    const response = await api.tracing.aggregate(
                        {
                            dateRange: {
                                date_from: new Date(window.currentStartMs).toISOString(),
                                date_to: new Date(window.currentEndMs).toISOString(),
                            },
                            serviceNames:
                                values.filters.serviceNames.length > 0 ? values.filters.serviceNames : undefined,
                            filterGroup: values.queryFilterGroup as PropertyGroupFilter,
                            compareFilter: {
                                compare,
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
                    // The sparkline counts root spans in 'traces' mode and every span in 'spans' mode
                    // (via rootSpans below), so it depends on the data scope (date range, services,
                    // filters) AND the view mode — but not on sort or compare. Skip the re-fetch (and
                    // its spinner overlay) only when a sort/compare toggle re-runs the query without
                    // changing scope or view mode.
                    const scopeKey = JSON.stringify([
                        values.utcDateRange,
                        values.filters.serviceNames,
                        values.queryFilterGroup,
                        values.filters.viewMode,
                    ])
                    if (scopeKey === cache.sparklineScope) {
                        return values.rawSparklineData
                    }

                    const controller = new AbortController()
                    actions.cancelInProgressSparkline(controller)

                    const response = await api.tracing.sparkline(
                        {
                            dateRange: values.utcDateRange,
                            serviceNames:
                                values.filters.serviceNames.length > 0 ? values.filters.serviceNames : undefined,
                            filterGroup: values.queryFilterGroup as PropertyGroupFilter,
                            rootSpans: values.filters.viewMode === 'traces',
                        },
                        controller.signal
                    )

                    actions.setSparklineAbortController(null)
                    // Record the scope only after a successful fetch, so a failed/aborted request retries.
                    cache.sparklineScope = scopeKey
                    return response.results
                },
            },
        ],
        matchingCounts: [
            { count: 0, traceCount: 0 } as { count: number; traceCount: number },
            {
                fetchMatchingCounts: async () => {
                    // The count is view-mode-independent — it returns both span and trace counts in one
                    // response, and the label selects which to show. So a Traces/Spans (or sort/compare)
                    // toggle that re-runs the query must not re-hit the endpoint; only the data scope
                    // (date range, services, filters) changes the result. Skip the fetch when unchanged.
                    const scopeKey = JSON.stringify([
                        values.utcDateRange,
                        values.filters.serviceNames,
                        values.queryFilterGroup,
                    ])
                    if (scopeKey === cache.matchingCountsScope) {
                        return values.matchingCounts
                    }

                    const controller = new AbortController()
                    actions.cancelInProgressMatchingCounts(controller)

                    const response = await api.tracing.count(
                        {
                            dateRange: values.utcDateRange,
                            serviceNames:
                                values.filters.serviceNames.length > 0 ? values.filters.serviceNames : undefined,
                            filterGroup: values.queryFilterGroup as PropertyGroupFilter,
                        },
                        controller.signal
                    )

                    actions.setMatchingCountsAbortController(null)
                    // Record the scope only after a successful fetch, so a failed/aborted request retries.
                    cache.matchingCountsScope = scopeKey
                    return response
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
                            filterGroup: values.queryFilterGroup as PropertyGroupFilter,
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
        // Total matching the filters, in the unit the list is showing: distinct traces in 'traces'
        // mode, individual spans in 'spans' mode. Fed by the count endpoint, which returns both.
        totalMatchingFilters: [
            (s) => [s.matchingCounts, s.filters],
            (matchingCounts: { count: number; traceCount: number }, filters: TracingFilters): number =>
                filters.viewMode === 'spans' ? matchingCounts.count : matchingCounts.traceCount,
        ],
        durationHistogramData: [
            (s) => [s.rawDurationHistogram],
            (rows: DurationHistogramRow[]): TracingDurationHistogramData => pivotDurationHistogram(rows, dataColorVars),
        ],
        // The rows the list renders. 'traces' mode shows root spans only (one row per trace);
        // 'spans' mode shows every matching span (root and child) flat. The fetch passes flatSpans
        // to match, so in 'spans' mode the loaded spans are already the flat set.
        listRows: [
            (s) => [s.spans, s.filters],
            (spans: Span[], filters: TracingFilters): Span[] => {
                return filters.viewMode === 'spans' ? spans : spans.filter((s) => s.is_root_span)
            },
        ],
        // Memoized separately so visibleRowDurationRange (recomputed on every scroll tick) doesn't
        // re-allocate the durations array — this only changes when the loaded rows do.
        listRowDurations: [
            (s) => [s.listRows],
            (listRows: Span[]): number[] => listRows.map((span) => span.duration_nano),
        ],
        // Single owner of the "show the duration histogram?" rule — the fetch decision, the
        // highlight selector, and the scene's rendering all derive from this one place.
        // An active comparison replaces the span list with the aggregate table, so the histogram
        // (which mirrors the duration-sorted list) only applies outside it.
        isDurationMode: [
            (s) => [s.filters, s.compareActive],
            (filters: TracingFilters, compareActive: boolean): boolean =>
                filters.orderBy === 'duration' && !compareActive,
        ],

        // Duration range covered by the currently-visible rows — the duration-space sibling of
        // visibleRowDateRange below. When sorted by duration the visible rows are contiguous in
        // duration space, so the histogram can sweep a highlight across the distribution as the
        // user scrolls (the same interaction the time sparkline has under timestamp sort).
        visibleRowDurationRange: [
            (s) => [s.visibleRowRange, s.listRowDurations, s.isDurationMode],
            (
                visibleRowRange: VisibleRowRange | null,
                listRowDurations: number[],
                isDurationMode: boolean
            ): VisibleDurationRange | null => {
                if (!isDurationMode) {
                    return null
                }
                return visibleDurationRange(visibleRowRange, listRowDurations)
            },
        ],

        // Date range covered by the currently-visible (scrolled-into-view) rows, so the sparkline can
        // highlight the window the list is showing (mirrors the logs viewer). Only meaningful when the
        // list is time-ordered — under duration (or any non-timestamp) sort, consecutive rows aren't
        // contiguous in time, so the highlight would be meaningless. Suppress it then; the duration
        // histogram (visibleRowDurationRange above) covers the duration-sorted case.
        visibleRowDateRange: [
            (s) => [s.visibleRowRange, s.listRows, s.orderBy],
            (
                visibleRowRange: VisibleRowRange | null,
                listRows: Span[],
                orderBy: TracingOrderBy
            ): VisibleSpanTimeRange | null => {
                if (orderBy !== 'timestamp' || !visibleRowRange || listRows.length === 0) {
                    return null
                }
                const startIndex = Math.max(0, Math.min(visibleRowRange.startIndex, listRows.length - 1))
                const stopIndex = Math.max(0, Math.min(visibleRowRange.stopIndex, listRows.length - 1))
                const a = listRows[startIndex]?.timestamp
                const b = listRows[stopIndex]?.timestamp
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
            // The time sparkline is always fetched — it keeps the chart warm when the user flips back
            // to timestamp sort. Duration sort additionally fetches the histogram that replaces it
            // visually. The count endpoint feeds the "N traces/spans matching filters" label.
            actions.fetchSparkline()
            actions.fetchMatchingCounts()
            if (values.isDurationMode) {
                actions.fetchDurationHistogram()
            }
            if (values.compareActive) {
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
        cancelInProgressMatchingCounts: ({ controller }) => {
            if (values.matchingCountsAbortController !== null) {
                values.matchingCountsAbortController.abort(NEW_QUERY_STARTED_ERROR_MESSAGE)
            }
            actions.setMatchingCountsAbortController(controller)
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
            captureTracingResults(values.listRows.length, 'spans')
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
        fetchMatchingCountsFailure: ({ error }) => {
            if (!isUserInitiatedError(error)) {
                lemonToast.error(`Failed to load the matching count: ${error}`)
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
            if (values.matchingCountsAbortController) {
                values.matchingCountsAbortController.abort('unmounting component')
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
