import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { dataColorVars } from 'lib/colors'
import { humanFriendlyDetailedTime } from 'lib/utils'

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

const DEFAULT_PAGE_SIZE = 100
export const PREFETCH_SPANS = 20
const NEW_QUERY_STARTED_ERROR_MESSAGE = 'new query started' as const

function isUserInitiatedError(error: unknown): boolean {
    const errorStr = String(error).toLowerCase()
    return error === NEW_QUERY_STARTED_ERROR_MESSAGE || errorStr.includes('abort')
}

export const tracingDataLogic = kea<tracingDataLogicType>([
    path(['products', 'tracing', 'frontend', 'tracingDataLogic']),

    connect({
        values: [tracingFiltersLogic, ['filters', 'utcDateRange']],
    }),

    actions({
        runQuery: true,
        fetchNextPage: true,
        clearSpans: true,
        cancelInProgressSpans: (controller: AbortController | null) => ({ controller }),
        cancelInProgressSparkline: (controller: AbortController | null) => ({ controller }),
        setSpansAbortController: (controller: AbortController | null) => ({ controller }),
        setSparklineAbortController: (controller: AbortController | null) => ({ controller }),
        setHasMoreToLoad: (hasMore: boolean) => ({ hasMore }),
        setNextCursor: (cursor: string | null) => ({ cursor }),
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
    }),

    loaders(({ values, actions }) => ({
        spans: [
            [] as Span[],
            {
                clearSpans: () => [],
                fetchSpans: async () => {
                    const controller = new AbortController()
                    actions.cancelInProgressSpans(controller)

                    const response = await api.tracing.listSpans({
                        dateRange: values.utcDateRange,
                        orderBy: values.filters.orderBy,
                        serviceNames: values.filters.serviceNames.length > 0 ? values.filters.serviceNames : undefined,
                        filterGroup: values.filters.filterGroup as PropertyGroupFilter,
                        prefetchSpans: PREFETCH_SPANS,
                        limit: DEFAULT_PAGE_SIZE,
                    })

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

                    const response = await api.tracing.listSpans({
                        dateRange: values.utcDateRange,
                        orderBy: values.filters.orderBy,
                        serviceNames: values.filters.serviceNames.length > 0 ? values.filters.serviceNames : undefined,
                        filterGroup: values.filters.filterGroup as PropertyGroupFilter,
                        limit: DEFAULT_PAGE_SIZE,
                        after: values.nextCursor,
                    })

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
        rawSparklineData: [
            [] as SparklineRow[],
            {
                fetchSparkline: async () => {
                    const controller = new AbortController()
                    actions.cancelInProgressSparkline(controller)

                    const response = await api.tracing.sparkline({
                        dateRange: values.utcDateRange,
                        serviceNames: values.filters.serviceNames.length > 0 ? values.filters.serviceNames : undefined,
                        filterGroup: values.filters.filterGroup as PropertyGroupFilter,
                    })

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
    }),

    listeners(({ actions, values }) => ({
        runQuery: () => {
            actions.clearSpans()
            actions.fetchSpans()
            actions.fetchSparkline()
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
        fetchSpansFailure: ({ error }) => {
            if (!isUserInitiatedError(error)) {
                lemonToast.error(`Failed to load traces: ${error}`)
            }
        },
        fetchSparklineFailure: ({ error }) => {
            if (!isUserInitiatedError(error)) {
                // Sparkline failures are non-critical, don't show toast
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
        },
    })),
])
