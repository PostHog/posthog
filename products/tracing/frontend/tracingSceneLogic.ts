import equal from 'fast-deep-equal'
import { actions, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { router, urlToAction } from 'kea-router'
import posthog from 'posthog-js'

import { DEFAULT_UNIVERSAL_GROUP_FILTER } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { tabAwareScene } from 'lib/logic/scenes/tabAwareScene'
import { trackedActionToUrl } from 'lib/logic/scenes/trackedActionToUrl'
import { parseTagsFilter } from 'lib/utils'
import { Params } from 'scenes/sceneTypes'

import { Breadcrumb } from '~/types'

import { PREFETCH_SPANS, tracingDataLogic } from './tracingDataLogic'
import { DEFAULT_DATE_RANGE, DEFAULT_ORDER_BY, DEFAULT_SERVICE_NAMES, tracingFiltersLogic } from './tracingFiltersLogic'
import type { tracingSceneLogicType } from './tracingSceneLogicType'
import type { Span } from './types'

export interface TracingSceneLogicProps {
    tabId?: string
}

export const tracingSceneLogic = kea<tracingSceneLogicType>([
    props({} as TracingSceneLogicProps),
    path(['products', 'tracing', 'frontend', 'tracingSceneLogic']),
    tabAwareScene(),

    connect((p: TracingSceneLogicProps) => ({
        values: [
            tracingDataLogic({ tabId: p.tabId }),
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
                'aggregation',
                'aggregationLoading',
                'spanTree',
                'spanTreeLoading',
                'visibleRowDateRange',
            ],
            tracingFiltersLogic({ tabId: p.tabId }),
            ['filters', 'utcDateRange', 'sparklineWindowMs', 'currentWindowMs', 'previousWindowMs'],
        ],
        actions: [
            tracingDataLogic({ tabId: p.tabId }),
            ['runQuery', 'fetchNextPage', 'loadTraceSpans', 'fetchAggregation', 'fetchSpanTree', 'setVisibleRowRange'],
            tracingFiltersLogic({ tabId: p.tabId }),
            [
                'setDateRange',
                'setServiceNames',
                'setFilterGroup',
                'setOrderBy',
                'setCompareMode',
                'setOverlayWindows',
                'setFilters',
            ],
        ],
    })),

    actions({
        toggleExpandSpan: (uuid: string) => ({ uuid }),
        openTraceModal: (traceId: string) => ({ traceId }),
        closeTraceModal: true,
        openCompareFlame: (spanName: string, serviceName: string) => ({ spanName, serviceName }),
        closeCompareFlame: true,
        syncUrlAndRunQuery: true,
        handleFilterChange: (filterType: string, extraProps?: Record<string, unknown>) => ({ filterType, extraProps }),
    }),

    reducers({
        expandedSpanIds: [
            {} as Record<string, boolean>,
            {
                toggleExpandSpan: (state, { uuid }) => {
                    const next = { ...state }
                    if (next[uuid]) {
                        delete next[uuid]
                    } else {
                        next[uuid] = true
                    }
                    return next
                },
                // Drop stale expansion state whenever the span list is refetched.
                runQuery: () => ({}),
            },
        ],
        selectedTraceId: [
            null as string | null,
            {
                openTraceModal: (_, { traceId }) => traceId,
                closeTraceModal: () => null,
            },
        ],
        compareFlameSpanName: [
            null as string | null,
            {
                openCompareFlame: (_, { spanName }) => spanName,
                closeCompareFlame: () => null,
            },
        ],
        compareFlameServiceName: [
            null as string | null,
            {
                openCompareFlame: (_, { serviceName }) => serviceName,
                closeCompareFlame: () => null,
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
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: 'tracing',
                    name: 'Tracing',
                    iconType: 'tracing',
                },
            ],
        ],
    }),

    listeners(({ actions, values }) => ({
        openTraceModal: ({ traceId }) => {
            posthog.capture('tracing trace opened')
            const prefetchedSpans = values.spans.filter((s: Span) => s.trace_id === traceId)
            if (prefetchedSpans.length >= PREFETCH_SPANS) {
                actions.loadTraceSpans(traceId)
            }
        },
        openCompareFlame: ({ spanName, serviceName }) => {
            actions.fetchSpanTree({ spanName, serviceName })
        },
        handleFilterChange: ({ filterType, extraProps }) => {
            posthog.capture('tracing filter changed', { filter_type: filterType, ...extraProps })
            actions.syncUrlAndRunQuery()
        },
        setDateRange: () => actions.handleFilterChange('date_range'),
        setServiceNames: () => actions.handleFilterChange('service_names'),
        setFilterGroup: () => actions.handleFilterChange('filter_group'),
        setOrderBy: () => actions.handleFilterChange('order_by'),
        setCompareMode: ({ compareMode }) => actions.handleFilterChange('compare_mode', { enabled: compareMode }),
        setOverlayWindows: () => {
            // Overlay drags only refetch the aggregation — the sparkline canvas range
            // stays fixed while the user moves windows around within it. If the compare-flame
            // modal is open we also refetch its tree so it doesn't display stale windows.
            actions.fetchAggregation()
            if (values.compareFlameSpanName && values.compareFlameServiceName) {
                actions.fetchSpanTree({
                    spanName: values.compareFlameSpanName,
                    serviceName: values.compareFlameServiceName,
                })
            }
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

            const compareFromUrl = searchParams.compare === 'true' || searchParams.compare === true
            if (compareFromUrl !== values.filters.compareMode) {
                filtersFromUrl.compareMode = compareFromUrl
                hasChanges = true
            }

            if (hasChanges) {
                actions.setFilters(filtersFromUrl)
            } else if (!values.hasRunQuery) {
                actions.runQuery()
            }
        },
    })),

    trackedActionToUrl(({ values, actions }) => {
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
            if (values.filters.compareMode) {
                searchParams.compare = 'true'
            }

            actions.runQuery()
            return [router.values.location.pathname, searchParams, router.values.hashParams, { replace: true }]
        }

        return {
            syncUrlAndRunQuery: () => buildUrl(),
        }
    }),
])
