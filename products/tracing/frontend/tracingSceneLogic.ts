import equal from 'fast-deep-equal'
import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { DEFAULT_UNIVERSAL_GROUP_FILTER } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { parseTagsFilter } from 'lib/utils'
import { Params } from 'scenes/sceneTypes'

import {
    FilterLogicalOperator,
    PropertyFilterType,
    PropertyOperator,
    SpanPropertyFilter,
    UniversalFiltersGroup,
} from '~/types'

import { PREFETCH_SPANS, tracingDataLogic } from './tracingDataLogic'
import {
    DEFAULT_DATE_RANGE,
    DEFAULT_HEATMAP_Y_SCALE,
    DEFAULT_ORDER_BY,
    DEFAULT_SERVICE_NAMES,
    tracingFiltersLogic,
} from './tracingFiltersLogic'
import type { TracingChartMode, TracingSelectedRegion } from './tracingFiltersLogic'
import type { tracingSceneLogicType } from './tracingSceneLogicType'
import type { Span } from './types'

function mergeDurationFilters(group: UniversalFiltersGroup, loMs: number, hiMs: number): UniversalFiltersGroup {
    const inner = group.values[0]
    if (!inner || inner.type !== FilterLogicalOperator.And || !('values' in inner)) {
        return group
    }
    const rest = inner.values.filter((f) => {
        if (typeof f === 'object' && f !== null && 'key' in f) {
            return (f as SpanPropertyFilter).key !== 'duration'
        }
        return true
    })
    const gt: SpanPropertyFilter = {
        type: PropertyFilterType.Span,
        key: 'duration',
        operator: PropertyOperator.GreaterThan,
        value: loMs,
    }
    const lt: SpanPropertyFilter = {
        type: PropertyFilterType.Span,
        key: 'duration',
        operator: PropertyOperator.LessThan,
        value: hiMs,
    }
    return {
        type: FilterLogicalOperator.And,
        values: [
            {
                type: FilterLogicalOperator.And,
                values: [...rest, gt, lt],
            },
        ],
    }
}

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
                'latencyHeatmapRows',
                'hasMoreToLoad',
                'hasRunQuery',
                'totalSpansMatchingFilters',
                'traceSpans',
                'traceSpansLoading',
                'bubbleUpRows',
                'bubbleUpRowsLoading',
            ],
            tracingFiltersLogic,
            ['filters', 'utcDateRange'],
            featureFlagLogic,
            ['featureFlags'],
        ],
        actions: [
            tracingDataLogic,
            ['runQuery', 'fetchNextPage', 'loadTraceSpans', 'fetchSparkline', 'fetchBubbleUp', 'clearBubbleUp'],
            tracingFiltersLogic,
            [
                'setDateRange',
                'setServiceNames',
                'setFilterGroup',
                'setOrderBy',
                'setFilters',
                'setChartMode',
                'setHeatmapYScale',
                'clearSelectedRegion',
            ],
            featureFlagLogic,
            ['setFeatureFlags'],
        ],
    }),

    actions({
        openTraceModal: (traceId: string) => ({ traceId }),
        closeTraceModal: true,
        syncUrlAndRunQuery: true,
        applyZoomFromSelectedRegion: (region: TracingSelectedRegion) => ({ region }),
        runBubbleUp: (region: TracingSelectedRegion) => ({ region }),
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
        defaultChartModeForTracing: [
            (s) => [s.featureFlags],
            (featureFlags): TracingChartMode => (featureFlags?.[FEATURE_FLAGS.TRACING] ? 'latency' : 'volume'),
        ],
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
        setChartMode: () => {
            actions.fetchSparkline()
            const searchParams = { ...router.values.searchParams } as Record<string, string | undefined>
            if (values.filters.chartMode === values.defaultChartModeForTracing) {
                delete searchParams.chart
            } else {
                searchParams.chart = values.filters.chartMode
            }
            router.actions.setSearchParams(searchParams, { replace: true })
        },
        setHeatmapYScale: () => {
            const searchParams = { ...router.values.searchParams } as Record<string, string | undefined>
            if (values.filters.heatmapYScale === DEFAULT_HEATMAP_Y_SCALE) {
                delete searchParams.heatmapY
            } else {
                searchParams.heatmapY = values.filters.heatmapYScale
            }
            router.actions.setSearchParams(searchParams, { replace: true })
        },
        applyZoomFromSelectedRegion: ({ region }) => {
            const loMs = region.duration_min_nano / 1e6
            const hiMs = region.duration_max_nano / 1e6
            actions.setDateRange({ date_from: region.time_from, date_to: region.time_to })
            actions.setFilterGroup(mergeDurationFilters(values.filters.filterGroup, loMs, hiMs))
            actions.clearSelectedRegion()
        },
        runBubbleUp: ({ region }) => {
            actions.clearBubbleUp()
            actions.fetchBubbleUp({ region })
        },
        setFeatureFlags: () => {
            const chartInUrl = router.values.searchParams.chart
            if (chartInUrl === 'latency' || chartInUrl === 'volume') {
                return
            }
            if (values.filters.chartMode !== values.defaultChartModeForTracing) {
                actions.setFilters({ chartMode: values.defaultChartModeForTracing })
            }
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

            if (searchParams.chart === 'latency' || searchParams.chart === 'volume') {
                if (searchParams.chart !== values.filters.chartMode) {
                    filtersFromUrl.chartMode = searchParams.chart
                    hasChanges = true
                }
            } else if (values.filters.chartMode !== values.defaultChartModeForTracing) {
                filtersFromUrl.chartMode = values.defaultChartModeForTracing
                hasChanges = true
            }

            if (searchParams.heatmapY === 'linear' || searchParams.heatmapY === 'log') {
                if (searchParams.heatmapY !== values.filters.heatmapYScale) {
                    filtersFromUrl.heatmapYScale = searchParams.heatmapY
                    hasChanges = true
                }
            } else if (values.filters.heatmapYScale !== DEFAULT_HEATMAP_Y_SCALE) {
                filtersFromUrl.heatmapYScale = DEFAULT_HEATMAP_Y_SCALE
                hasChanges = true
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
            if (values.filters.chartMode !== values.defaultChartModeForTracing) {
                searchParams.chart = values.filters.chartMode
            }
            if (values.filters.heatmapYScale !== DEFAULT_HEATMAP_Y_SCALE) {
                searchParams.heatmapY = values.filters.heatmapYScale
            }

            actions.runQuery()
            return [router.values.location.pathname, searchParams, router.values.hashParams, { replace: true }]
        }

        return {
            syncUrlAndRunQuery: () => buildUrl(),
        }
    }),
])
