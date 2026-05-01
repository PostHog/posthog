import equal from 'fast-deep-equal'
import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { DEFAULT_UNIVERSAL_GROUP_FILTER } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { parseTagsFilter } from 'lib/utils'
import { Params } from 'scenes/sceneTypes'

import { PREFETCH_SPANS, tracingDataLogic } from './tracingDataLogic'
import { DEFAULT_DATE_RANGE, DEFAULT_ORDER_BY, DEFAULT_SERVICE_NAMES, tracingFiltersLogic } from './tracingFiltersLogic'
import type { tracingSceneLogicType } from './tracingSceneLogicType'
import type { Span } from './types'

export const tracingSceneLogic = kea<tracingSceneLogicType>([
    path(['products', 'tracing', 'frontend', 'tracingSceneLogic']),

    connect({
        values: [
            tracingDataLogic,
            [
                'spans',
                'spansLoading',
                'rootSpans',
                'sparklineData',
                'sparklineLoading',
                'hasMoreToLoad',
                'hasRunQuery',
                'totalSpansMatchingFilters',
                'traceSpans',
                'traceSpansLoading',
            ],
            tracingFiltersLogic,
            ['filters', 'utcDateRange'],
        ],
        actions: [
            tracingDataLogic,
            ['runQuery', 'fetchNextPage', 'loadTraceSpans'],
            tracingFiltersLogic,
            ['setDateRange', 'setServiceNames', 'setFilterGroup', 'setOrderBy', 'setFilters'],
        ],
    }),

    actions({
        openTraceModal: (traceId: string) => ({ traceId }),
        closeTraceModal: true,
        syncUrlAndRunQuery: true,
    }),

    reducers({
        selectedTraceId: [
            null as string | null,
            {
                openTraceModal: (_, { traceId }) => traceId,
                closeTraceModal: () => null,
            },
        ],
    }),

    selectors({
        isTraceModalOpen: [
            (s) => [s.selectedTraceId],
            (selectedTraceId: string | null): boolean => selectedTraceId !== null,
        ],
        modalSpans: [
            (s) => [s.selectedTraceId, s.spans, s.traceSpans],
            (selectedTraceId: string | null, spans: Span[], traceSpans: Span[]): Span[] => {
                if (!selectedTraceId) {
                    return []
                }
                const filteredTraceSpans = traceSpans.filter((s) => s.trace_id === selectedTraceId)
                if (filteredTraceSpans.length > 0) {
                    return filteredTraceSpans
                }
                return spans.filter((s) => s.trace_id === selectedTraceId)
            },
        ],
        isLoadingFullTrace: [(s) => [s.traceSpansLoading], (traceSpansLoading: boolean): boolean => traceSpansLoading],
    }),

    listeners(({ actions, values }) => ({
        openTraceModal: ({ traceId }) => {
            const prefetchedSpans = values.spans.filter((s: Span) => s.trace_id === traceId)
            if (prefetchedSpans.length >= PREFETCH_SPANS) {
                actions.loadTraceSpans(traceId)
            }
        },
        setDateRange: () => {
            actions.syncUrlAndRunQuery()
        },
        setServiceNames: () => {
            actions.syncUrlAndRunQuery()
        },
        setFilterGroup: () => {
            actions.syncUrlAndRunQuery()
        },
        setOrderBy: () => {
            actions.syncUrlAndRunQuery()
        },
        setFilters: () => {
            actions.syncUrlAndRunQuery()
        },
    })),

    urlToAction(({ actions, values }) => ({
        '/tracing': (_, searchParams) => {
            const filtersFromUrl: Record<string, any> = {}
            let hasChanges = false

            if (searchParams.dateRange) {
                try {
                    const dateRange =
                        typeof searchParams.dateRange === 'string'
                            ? JSON.parse(searchParams.dateRange)
                            : searchParams.dateRange
                    if (!equal(dateRange, values.filters.dateRange)) {
                        filtersFromUrl.dateRange = dateRange
                        hasChanges = true
                    }
                } catch {
                    // Ignore malformed JSON
                }
            }

            if (searchParams.serviceNames) {
                const names = parseTagsFilter(searchParams.serviceNames)
                if (names && !equal(names, values.filters.serviceNames)) {
                    filtersFromUrl.serviceNames = names
                    hasChanges = true
                }
            } else if (!equal(DEFAULT_SERVICE_NAMES, values.filters.serviceNames)) {
                filtersFromUrl.serviceNames = DEFAULT_SERVICE_NAMES
                hasChanges = true
            }

            if (searchParams.filterGroup) {
                try {
                    const filterGroup =
                        typeof searchParams.filterGroup === 'string'
                            ? JSON.parse(searchParams.filterGroup)
                            : searchParams.filterGroup
                    if (!equal(filterGroup, values.filters.filterGroup)) {
                        filtersFromUrl.filterGroup = filterGroup
                        hasChanges = true
                    }
                } catch {
                    // Ignore malformed JSON
                }
            } else if (!equal(DEFAULT_UNIVERSAL_GROUP_FILTER, values.filters.filterGroup)) {
                filtersFromUrl.filterGroup = DEFAULT_UNIVERSAL_GROUP_FILTER
                hasChanges = true
            }

            if (searchParams.orderBy) {
                if (searchParams.orderBy !== values.filters.orderBy) {
                    filtersFromUrl.orderBy = searchParams.orderBy
                    hasChanges = true
                }
            }

            if (hasChanges) {
                actions.setFilters(filtersFromUrl)
            } else if (!values.hasRunQuery) {
                actions.runQuery()
            }
        },
    })),

    actionToUrl(({ values, actions }) => {
        const buildUrl = (): [string, Params, Record<string, any>, { replace: boolean }] => {
            const searchParams: Params = {}

            if (!equal(values.filters.dateRange, DEFAULT_DATE_RANGE)) {
                searchParams.dateRange = JSON.stringify(values.filters.dateRange)
            }
            if (!equal(values.filters.serviceNames, DEFAULT_SERVICE_NAMES)) {
                searchParams.serviceNames = values.filters.serviceNames
            }
            if (!equal(values.filters.filterGroup, DEFAULT_UNIVERSAL_GROUP_FILTER)) {
                searchParams.filterGroup = JSON.stringify(values.filters.filterGroup)
            }
            if (values.filters.orderBy !== DEFAULT_ORDER_BY) {
                searchParams.orderBy = values.filters.orderBy
            }

            actions.runQuery()
            return [router.values.location.pathname, searchParams, router.values.hashParams, { replace: true }]
        }

        return {
            syncUrlAndRunQuery: () => buildUrl(),
        }
    }),
])
