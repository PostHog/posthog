import equal from 'fast-deep-equal'
import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { router, urlToAction } from 'kea-router'
import posthog from 'posthog-js'

import { DEFAULT_UNIVERSAL_GROUP_FILTER } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { trackedActionToUrl } from 'lib/logic/scenes/trackedActionToUrl'
import { parseTagsFilter } from 'lib/utils/url'
import { Params } from 'scenes/sceneTypes'

import { Breadcrumb } from '~/types'

import { PREFETCH_SPANS, tracingDataLogic } from './tracingDataLogic'
import {
    DEFAULT_DATE_RANGE,
    DEFAULT_ORDER_BY,
    DEFAULT_ORDER_DIRECTION,
    DEFAULT_SERVICE_NAMES,
    DEFAULT_VIEW_MODE,
    tracingFiltersLogic,
} from './tracingFiltersLogic'
import type { tracingSceneLogicType } from './tracingSceneLogicType'
import type { Span } from './types'

export const tracingSceneLogic = kea<tracingSceneLogicType>([
    path(['products', 'tracing', 'frontend', 'tracingSceneLogic']),

    connect(() => ({
        values: [
            tracingDataLogic(),
            [
                'spans',
                'spansLoading',
                'listRows',
                'sparklineData',
                'sparklineLoading',
                'hasMoreToLoad',
                'hasRunQuery',
                'totalMatchingFilters',
                'traceSpans',
                'traceSpansLoading',
                'traceSpansLoadingMore',
                'traceSpansHasMore',
                'aggregation',
                'aggregationLoading',
                'spanTree',
                'spanTreeLoading',
                'visibleRowDateRange',
                'durationHistogramData',
                'durationHistogramLoading',
                'visibleRowDurationRange',
                'isDurationMode',
            ],
            tracingFiltersLogic(),
            ['filters', 'utcDateRange', 'sparklineWindowMs', 'currentWindowMs', 'previousWindowMs'],
        ],
        actions: [
            tracingDataLogic(),
            [
                'runQuery',
                'fetchNextPage',
                'loadTraceSpans',
                'loadMoreTraceSpans',
                'fetchAggregation',
                'fetchSpanTree',
                'setVisibleRowRange',
            ],
            tracingFiltersLogic(),
            [
                'setDateRange',
                'setServiceNames',
                'setFilterGroup',
                'setSort',
                'setViewMode',
                'setCompareMode',
                'setOverlayWindows',
                'setFilters',
            ],
        ],
    })),

    actions({
        openTrace: (traceId: string, options?: { spanId?: string | null; ts?: string | null }) => ({
            traceId,
            spanId: options?.spanId ?? null,
            ts: options?.ts ?? null,
        }),
        selectSpan: (spanId: string | null) => ({ spanId }),
        closeTrace: true,
        openCompareFlame: (spanName: string, serviceName: string) => ({ spanName, serviceName }),
        closeCompareFlame: true,
        syncUrlAndRunQuery: true,
        handleFilterChange: (filterType: string, extraProps?: Record<string, unknown>) => ({ filterType, extraProps }),
        setActiveTracingTab: (tab: 'traces' | 'operations') => ({ tab }),
    }),

    reducers({
        selectedTraceId: [
            null as string | null,
            {
                openTrace: (_, { traceId }) => traceId,
                closeTrace: () => null,
            },
        ],
        selectedSpanId: [
            null as string | null,
            {
                openTrace: (_, { spanId }) => spanId,
                selectSpan: (_, { spanId }) => spanId,
                closeTrace: () => null,
            },
        ],
        // Timestamp hint for the open trace — echoed into copy-links so cold loads can bound the
        // ClickHouse lookup (the spans table is time-keyed; OTel ids embed no timestamp).
        selectedTraceTs: [
            null as string | null,
            {
                openTrace: (_, { ts }) => ts,
                closeTrace: () => null,
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
        activeTracingTab: [
            'traces' as 'traces' | 'operations',
            {
                setActiveTracingTab: (_, { tab }) => tab,
            },
        ],
    }),

    selectors({
        isTraceOpen: [
            (s) => [s.selectedTraceId],
            (selectedTraceId: string | null): boolean => selectedTraceId !== null,
        ],
        openTraceSpans: [
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
        // The drawer's full-trace overlay should only show on the initial fetch — paging in more
        // spans (loadMoreTraceSpans) keeps the waterfall visible with its own bottom spinner.
        isLoadingFullTrace: [
            (s) => [s.traceSpansLoading, s.traceSpansLoadingMore],
            (traceSpansLoading: boolean, traceSpansLoadingMore: boolean): boolean =>
                traceSpansLoading && !traceSpansLoadingMore,
        ],
        // Only offer "load more" when the full-fetched spans for the open trace are what's displayed
        // — never for the small prefetch fallback, which is already the trace's complete span set.
        canLoadMoreTraceSpans: [
            (s) => [s.traceSpansHasMore, s.traceSpans, s.selectedTraceId],
            (traceSpansHasMore: boolean, traceSpans: Span[], selectedTraceId: string | null): boolean =>
                traceSpansHasMore &&
                !!selectedTraceId &&
                traceSpans.some((span: Span) => span.trace_id === selectedTraceId),
        ],
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
        openTrace: ({ traceId, ts }) => {
            posthog.capture('tracing trace opened')
            const prefetchedSpans = values.spans.filter((s: Span) => s.trace_id === traceId)
            // Zero prefetched spans = the trace isn't in the loaded list (cold link) — fetch it by
            // id. A full prefetch batch (>= PREFETCH_SPANS) may be truncated — fetch the rest.
            if (prefetchedSpans.length === 0 || prefetchedSpans.length >= PREFETCH_SPANS) {
                actions.loadTraceSpans({ traceId, ts })
            }
        },
        openCompareFlame: ({ spanName, serviceName }) => {
            actions.fetchSpanTree({ spanName, serviceName })
        },
        handleFilterChange: ({ filterType, extraProps }) => {
            posthog.capture('tracing filter changed', { filter_type: filterType, ...extraProps })
            actions.syncUrlAndRunQuery()
            // Keep the Operations aggregate in sync with filters/date while that tab is active.
            if (values.activeTracingTab === 'operations') {
                actions.fetchAggregation()
            }
        },
        setDateRange: () => actions.handleFilterChange('date_range'),
        setServiceNames: () => actions.handleFilterChange('service_names'),
        setFilterGroup: () => actions.handleFilterChange('filter_group'),
        setSort: ({ orderBy, orderDirection }) =>
            actions.handleFilterChange('sort', { column: orderBy, direction: orderDirection }),
        setViewMode: ({ viewMode }) => actions.handleFilterChange('view_mode', { mode: viewMode }),
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
        setActiveTracingTab: ({ tab }) => {
            if (tab === 'operations') {
                actions.fetchAggregation()
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

            if (searchParams.orderDirection) {
                if (searchParams.orderDirection !== values.filters.orderDirection) {
                    filtersFromUrl.orderDirection = searchParams.orderDirection
                    hasChanges = true
                }
            }

            const compareFromUrl = searchParams.compare === 'true' || searchParams.compare === true
            if (compareFromUrl !== values.filters.compareMode) {
                filtersFromUrl.compareMode = compareFromUrl
                hasChanges = true
            }

            const viewModeFromUrl = searchParams.view === 'spans' ? 'spans' : DEFAULT_VIEW_MODE
            if (viewModeFromUrl !== values.filters.viewMode) {
                filtersFromUrl.viewMode = viewModeFromUrl
                hasChanges = true
            }

            if (hasChanges) {
                actions.setFilters(filtersFromUrl)
            } else if (!values.hasRunQuery) {
                actions.runQuery()
            }

            // Drawer params. Guarded on a state/URL mismatch so the actionToUrl writes below don't
            // loop back through here, and so back/forward opens/closes the drawer correctly.
            const traceFromUrl = typeof searchParams.trace === 'string' ? searchParams.trace : null
            const spanFromUrl = typeof searchParams.span === 'string' ? searchParams.span : null
            if (traceFromUrl && traceFromUrl !== values.selectedTraceId) {
                actions.openTrace(traceFromUrl, {
                    spanId: spanFromUrl,
                    ts: typeof searchParams.ts === 'string' ? searchParams.ts : null,
                })
            } else if (traceFromUrl && spanFromUrl !== values.selectedSpanId) {
                // Same trace already open, but the URL's span anchor changed (e.g. a shared span
                // link to a trace the user already has open) — move the selection, don't reopen.
                actions.selectSpan(spanFromUrl)
            } else if (!traceFromUrl && values.selectedTraceId) {
                actions.closeTrace()
            }
        },
    })),

    trackedActionToUrl(({ values, actions }) => {
        // The drawer params (trace/span/ts) live alongside the filter params. They're written by
        // their own handlers below (which must NOT re-run the list query), and preserved by
        // buildUrl so a filter change doesn't silently strip an open drawer from the URL.
        const drawerParams = (): Params => {
            const params: Params = {}
            if (values.selectedTraceId) {
                params.trace = values.selectedTraceId
                if (values.selectedSpanId) {
                    params.span = values.selectedSpanId
                }
                if (values.selectedTraceTs) {
                    params.ts = values.selectedTraceTs
                }
            }
            return params
        }

        const buildUrl = (): [string, Params, Record<string, any>, { replace: boolean }] => {
            const searchParams: Params = { ...drawerParams() }

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
            if (values.filters.orderDirection !== DEFAULT_ORDER_DIRECTION) {
                searchParams.orderDirection = values.filters.orderDirection
            }
            if (values.filters.compareMode) {
                searchParams.compare = 'true'
            }
            if (values.filters.viewMode !== DEFAULT_VIEW_MODE) {
                searchParams.view = values.filters.viewMode
            }

            actions.runQuery()
            return [router.values.location.pathname, searchParams, router.values.hashParams, { replace: true }]
        }

        // Merge the drawer's state into the CURRENT url (filters untouched, no query re-run).
        // Opening/closing pushes a history entry (back closes the drawer); span selection replaces
        // (clicking around a waterfall shouldn't spam history).
        const drawerUrl = (replace: boolean): [string, Params, Record<string, any>, { replace: boolean }] => {
            const { trace, span, ts, ...rest } = router.values.searchParams
            return [
                router.values.location.pathname,
                { ...rest, ...drawerParams() },
                router.values.hashParams,
                { replace },
            ]
        }

        return {
            syncUrlAndRunQuery: () => buildUrl(),
            openTrace: () => drawerUrl(false),
            selectSpan: () => drawerUrl(true),
            closeTrace: () => drawerUrl(false),
        }
    }),
])
