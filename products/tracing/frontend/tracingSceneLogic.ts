import equal from 'fast-deep-equal'
import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { router, urlToAction } from 'kea-router'

import { DEFAULT_UNIVERSAL_GROUP_FILTER } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { trackedActionToUrl } from 'lib/logic/scenes/trackedActionToUrl'
import { parseTagsFilter } from 'lib/utils/url'
import { Params } from 'scenes/sceneTypes'

import { Breadcrumb } from '~/types'

import { tracingDataLogic } from './tracingDataLogic'
import {
    DEFAULT_CUSTOM_COMPARISON,
    DEFAULT_DATE_RANGE,
    DEFAULT_ORDER_BY,
    DEFAULT_ORDER_DIRECTION,
    DEFAULT_SERVICE_NAMES,
    DEFAULT_VIEW_MODE,
    parseComparison,
    serializeComparison,
    TRACING_SCENE_VIEWER_ID,
    type TracingComparison,
    tracingFiltersLogic,
} from './tracingFiltersLogic'
import type { tracingSceneLogicType } from './tracingSceneLogicType'
import { tracingViewerLogic } from './tracingViewerLogic'

export const tracingSceneLogic = kea<tracingSceneLogicType>([
    path(['products', 'tracing', 'frontend', 'tracingSceneLogic']),

    // The scene binds to the viewer-default instances of the keyed filter/data/viewer logics.
    // It owns ALL URL sync — the keyed logics are URL-free so they can be embedded anywhere;
    // this logic translates URL params to their actions and their actions back to URL writes.
    // Mirrors the logsSceneLogic / logsViewerLogic boundary.
    connect(() => ({
        values: [
            tracingDataLogic({ id: TRACING_SCENE_VIEWER_ID }),
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
            tracingFiltersLogic({ id: TRACING_SCENE_VIEWER_ID }),
            ['filters', 'utcDateRange', 'sparklineWindowMs', 'currentWindowMs', 'previousWindowMs', 'compareActive'],
            tracingViewerLogic({ id: TRACING_SCENE_VIEWER_ID }),
            [
                'selectedTraceId',
                'selectedSpanId',
                'selectedTraceTs',
                'isTraceOpen',
                'openTraceSpans',
                'isLoadingFullTrace',
                'canLoadMoreTraceSpans',
                'compareFlameSpanName',
                'compareFlameServiceName',
            ],
        ],
        actions: [
            tracingDataLogic({ id: TRACING_SCENE_VIEWER_ID }),
            [
                'runQuery',
                'fetchNextPage',
                'loadTraceSpans',
                'loadMoreTraceSpans',
                'fetchAggregation',
                'fetchSpanTree',
                'setVisibleRowRange',
                'handleFilterChange',
            ],
            tracingFiltersLogic({ id: TRACING_SCENE_VIEWER_ID }),
            [
                'setDateRange',
                'setServiceNames',
                'setFilterGroup',
                'setSort',
                'setViewMode',
                'setComparison',
                'updateComparisonWindows',
                'setFilters',
            ],
            tracingViewerLogic({ id: TRACING_SCENE_VIEWER_ID }),
            ['openTrace', 'selectSpan', 'closeTrace', 'openCompareFlame', 'closeCompareFlame'],
        ],
    })),

    actions({
        syncUrl: true,
        setActiveTracingTab: (tab: 'traces' | 'operations') => ({ tab }),
    }),

    reducers({
        activeTracingTab: [
            'traces' as 'traces' | 'operations',
            {
                setActiveTracingTab: (_, { tab }) => tab,
            },
        ],
    }),

    selectors({
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
        // The keyed data logic already captured the interaction and re-ran the query;
        // the scene's jobs are the URL write and scene-tab side effects.
        handleFilterChange: () => {
            actions.syncUrl()
            // Keep the Operations aggregate in sync with filters/date while that tab is active.
            // Full range: the Operations view always covers the whole selected range, even while
            // a (traces-tab) comparison is active.
            //
            // This MUST run after the data logic's handleFilterChange listener. When a comparison
            // is active, that listener synchronously runs runQuery, whose listener fires a windowed
            // fetchAggregation(); every fetchAggregation aborts the previous one, so the last
            // dispatched wins. The data logic mounts before this scene logic, so its listener runs
            // first and the full-range fetch here beats the windowed one deterministically —
            // otherwise the Operations table would divide by the narrow compare sub-window.
            if (values.activeTracingTab === 'operations') {
                actions.fetchAggregation({ fullRange: true })
            }
        },
        setFilters: () => {
            actions.syncUrl()
        },
        setActiveTracingTab: ({ tab }) => {
            if (tab === 'operations') {
                actions.fetchAggregation({ fullRange: true })
            } else if (values.compareActive) {
                // Returning to the traces tab with a comparison active: the aggregation state
                // holds the operations full-range data — refetch the windowed compare version.
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

            // Legacy `compare=true` links map to the custom-windows preset; everything else
            // round-trips through parse/serializeComparison so future modes don't touch this file.
            const legacyComparisonFromUrl: TracingComparison | null =
                searchParams.compare === 'true' || searchParams.compare === true ? DEFAULT_CUSTOM_COMPARISON : null
            let comparisonFromUrl = legacyComparisonFromUrl
            // A malformed (or unknown future-mode) comparison param falls back to the legacy
            // param, and failing that is ignored rather than clearing an active comparison —
            // matching how the dateRange/filterGroup handlers treat malformed JSON.
            let comparisonParamInvalid = false
            if (searchParams.comparison) {
                const parsed = parseComparison(searchParams.comparison)
                if (parsed) {
                    comparisonFromUrl = parsed
                } else if (!legacyComparisonFromUrl) {
                    comparisonParamInvalid = true
                }
            }
            if (
                !comparisonParamInvalid &&
                serializeComparison(comparisonFromUrl) !== serializeComparison(values.filters.comparison)
            ) {
                filtersFromUrl.comparison = comparisonFromUrl
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

    trackedActionToUrl(({ values }) => {
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
            const comparisonParam = serializeComparison(values.filters.comparison)
            if (comparisonParam) {
                searchParams.comparison = comparisonParam
            }
            if (values.filters.viewMode !== DEFAULT_VIEW_MODE) {
                searchParams.view = values.filters.viewMode
            }

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
            syncUrl: () => buildUrl(),
            openTrace: () => drawerUrl(false),
            selectSpan: () => drawerUrl(true),
            closeTrace: () => drawerUrl(false),
        }
    }),
])
