import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, combineUrl, router, urlToAction } from 'kea-router'
import posthog from 'posthog-js'

import type { BoxPlotDatum } from '@posthog/quill-charts'

import api from 'lib/api'
import { dateFilterToText } from 'lib/utils/dateFilters'
import {
    type IntervalOption,
    buildBucketKeys,
    intervalOptionsForWindow,
    lastBucketIsInProgress,
    normalizeBucket,
    parseIntervalParam,
    resolveInterval,
} from 'lib/utils/timeBuckets'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import {
    MCPToolCategoryCountItem,
    MCPToolCategoryItem,
    MCPToolQualityDailyStatItem,
    MCPToolQualityRowItem,
    MCPToolQualityRowsQueryResponse,
    MCPToolQualitySortColumn,
    NodeKind,
} from '~/queries/schema/schema-general'
import { IntervalType } from '~/types'

import { type MCPSharedQueryFilters, mcpAnalyticsFiltersLogic } from './mcpAnalyticsFiltersLogic'

export interface CategoryCount {
    category: string
    calls: number
}

export interface ScopeShare {
    inScope: number
    total: number
    pct: number | null
}

export type SortDirection = 'ASC' | 'DESC'

export interface SortState {
    column: ToolQualitySortColumn
    direction: SortDirection
}

export interface DateFilter {
    dateFrom: string | null
    dateTo: string | null
}

interface ToolRowsPage extends MCPToolQualityRowsQueryResponse {
    pageIndex: number
}

// Carry the selected window across navigation as date_from / date_to, plus the grouping interval
// when one is pinned, mirroring the tab's actionToUrl. Only set them when present so a cleared range
// and an auto interval stay out of the URL. `properties` and `filter_test_accounts` ride along
// straight off the current URL, since mcpAnalyticsFiltersLogic's actionToUrl already keeps them
// there, so a link between tabs never re-encodes them from state and risks drifting from what's applied.
export function mcpDateSearchParams(dateFilter: DateFilter, interval?: IntervalType | null): Record<string, any> {
    const { properties, filter_test_accounts } = router.values.currentLocation.searchParams
    const params: Record<string, any> = {}
    if (properties !== undefined) {
        params.properties = properties
    }
    if (filter_test_accounts !== undefined) {
        params.filter_test_accounts = filter_test_accounts
    }
    if (dateFilter.dateFrom) {
        params.date_from = dateFilter.dateFrom
    }
    if (dateFilter.dateTo) {
        params.date_to = dateFilter.dateTo
    }
    if (interval) {
        params.interval = interval
    }
    return params
}

function mcpToolNavigationParams(dateFilter: DateFilter, interval?: IntervalType | null): Record<string, any> {
    const { properties, filter_test_accounts } = router.values.currentLocation.searchParams
    return {
        ...mcpDateSearchParams(dateFilter, interval),
        ...(properties !== undefined ? { properties } : {}),
        ...(filter_test_accounts !== undefined ? { filter_test_accounts } : {}),
    }
}

// Link from the Tool quality tab to an individual tool's report, keeping the date filter and pinned
// interval so the tool page opens on the same window and granularity.
export function mcpToolReportUrl(tool: string, dateFilter: DateFilter, interval?: IntervalType | null): string {
    return combineUrl(urls.mcpAnalyticsTool(tool), mcpToolNavigationParams(dateFilter, interval)).url
}

// Link back from a tool report to the Tool quality tab, restoring the date filter and interval.
export function mcpToolQualityUrlWithDates(dateFilter: DateFilter, interval?: IntervalType | null): string {
    return combineUrl(urls.mcpAnalyticsToolQuality(), mcpToolNavigationParams(dateFilter, interval)).url
}

export type ToolQualityRow = MCPToolQualityRowItem
export type ToolQualitySortColumn = MCPToolQualitySortColumn

export interface DailyToolStat {
    day: string
    calls: number
    errors: number
    p50: number
    p95: number
    p99: number
    min?: number | null
    p25?: number | null
    mean?: number | null
    p75?: number | null
    max?: number | null
}

export interface DailyChartData {
    labels: string[]
    calls: number[]
    errors: number[]
    errorRate: number[]
    successRate: number[]
    p50: number[]
    p95: number[]
    p99: number[]
    latencyBoxes: (BoxPlotDatum | null)[]
}

export type ChartViewChange =
    | { chart: 'calls'; view: 'counts' | 'percentage' }
    | { chart: 'successRate'; view: 'full' | 'zoom' }
    | { chart: 'latency'; view: 'lines' | 'boxPlot' }

export type ChartViews = { [C in ChartViewChange as C['chart']]: C['view'] }

export const DEFAULT_CHART_VIEWS: ChartViews = { calls: 'counts', successRate: 'full', latency: 'lines' }

const DEFAULT_DATE_FILTER: DateFilter = { dateFrom: '-7d', dateTo: null }
const DEFAULT_SORT: SortState = { column: 'total_calls', direction: 'DESC' }
export const TOOL_QUALITY_PAGE_SIZE = 50

// Pivot per-bucket rows onto the full set of interval buckets spanning the selected window:
// ClickHouse only returns buckets that had events, so `bucketKeys` (built from the window at the
// active interval) keeps the x-axis linear and covering the whole range regardless of granularity.
// Counts fill with 0 (genuinely no activity); rate and latency fill with NaN so the chart skips the
// point instead of drawing a misleading dip to zero. Rows match by normalized bucket key, so day,
// hour, and minute intervals all line up.
export function buildDailyChartData(dailyStats: DailyToolStat[], bucketKeys: string[]): DailyChartData {
    const byBucket = new Map(dailyStats.map((r) => [normalizeBucket(r.day), r]))
    const rows = bucketKeys.map((k) => byBucket.get(k))
    return {
        labels: bucketKeys,
        calls: rows.map((r) => r?.calls ?? 0),
        errors: rows.map((r) => r?.errors ?? 0),
        errorRate: rows.map((r) => (r && r.calls ? (r.errors / r.calls) * 100 : NaN)),
        successRate: rows.map((r) => (r && r.calls ? ((r.calls - r.errors) / r.calls) * 100 : NaN)),
        p50: rows.map((r) => (r ? r.p50 : NaN)),
        p95: rows.map((r) => (r ? r.p95 : NaN)),
        p99: rows.map((r) => (r ? r.p99 : NaN)),
        latencyBoxes: rows.map((r, i) => (r ? latencyBox(r, bucketKeys[i]) : null)),
    }
}

// Whiskers stop at p99 so one very slow call does not flatten every box.
function latencyBox(row: DailyToolStat, day: string): BoxPlotDatum | null {
    const { min, p25, mean, p75, max } = row
    if (min == null || p25 == null || mean == null || p75 == null || max == null) {
        return null
    }
    return { day, min, p25, median: row.p50, mean, p75, max, whiskerMax: row.p99 }
}

// BoxPlotDatum has no partial style like the line series' `stroke.partial`, so a still-collecting
// bucket is dropped outright rather than drawn as a settled box.
export function maskIncompleteLatencyBox(
    boxes: (BoxPlotDatum | null)[],
    incompleteTail: boolean
): (BoxPlotDatum | null)[] {
    if (!incompleteTail) {
        return boxes
    }
    return boxes.map((box, i) => (i === boxes.length - 1 ? null : box))
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface mcpAnalyticsToolQualityLogicValues {
    sharedQueryFilters: MCPSharedQueryFilters // mcpAnalyticsFiltersLogic
    availableCategories: string[]
    availableCategoriesLoading: boolean
    categoryCounts: CategoryCount[]
    categoryCountsLoading: boolean
    chartViews: ChartViews
    dailyChartData: DailyChartData
    dailyStats: DailyToolStat[]
    dailyStatsLoading: boolean
    dateFilter: DateFilter
    dateRangeLabel: string
    incompleteTail: boolean
    interval: IntervalType
    intervalOptions: IntervalOption[]
    latencyBoxes: (BoxPlotDatum | null)[]
    loadedToolQualityPageIndex: number
    pinnedInterval: IntervalType | null
    scopeShare: ScopeShare
    searchTerm: string
    selectedCategories: string[]
    selectedTool: string | null
    toolQualityPageIndex: number
    toolQualitySort: SortState
    toolRows: MCPToolQualityRowItem[]
    toolRowsPage: ToolRowsPage | null
    toolRowsPageLoading: boolean
    toolRowsPreviousTotalSessions: number
    toolRowsTotalCount: number
    toolRowsTotalSessions: number
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface mcpAnalyticsToolQualityLogicActions {
    hydrateFilters: (
        filterTestAccountsOverride: boolean | null,
        propertyFilters: import('~/types').AnyPropertyFilter[]
    ) => {
        filterTestAccountsOverride: boolean | null
        propertyFilters: import('~/types').AnyPropertyFilter[]
    } // mcpAnalyticsFiltersLogic
    setFilterTestAccounts: (filterTestAccounts: boolean | null) => {
        filterTestAccounts: boolean | null
    } // mcpAnalyticsFiltersLogic
    setPropertyFilters: (properties: import('~/types').AnyPropertyFilter[]) => {
        properties: import('~/types').AnyPropertyFilter[]
    } // mcpAnalyticsFiltersLogic
    loadAvailableCategories: (_: void) => void
    loadAvailableCategoriesFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadAvailableCategoriesSuccess: (
        availableCategories: string[],
        payload?: void
    ) => {
        availableCategories: string[]
        payload?: void
    }
    loadCategoryCounts: (_: void) => void
    loadCategoryCountsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadCategoryCountsSuccess: (
        categoryCounts: CategoryCount[],
        payload?: void
    ) => {
        categoryCounts: CategoryCount[]
        payload?: void
    }
    loadDailyStats: (_: void) => void
    loadDailyStatsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadDailyStatsSuccess: (
        dailyStats: DailyToolStat[],
        payload?: void
    ) => {
        dailyStats: DailyToolStat[]
        payload?: void
    }
    loadToolRowsPage: (_: void) => void
    loadToolRowsPageFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadToolRowsPageSuccess: (
        toolRowsPage: ToolRowsPage,
        payload?: void
    ) => {
        toolRowsPage: ToolRowsPage
        payload?: void
    }
    reloadAll: () => {
        value: true
    }
    setChartView: (change: ChartViewChange) => ChartViewChange
    setDateFilter: (
        dateFrom: string | null,
        dateTo: string | null
    ) => {
        dateFrom: string | null
        dateTo: string | null
    }
    setPinnedInterval: (interval: IntervalType | null) => {
        interval: IntervalType | null
    }
    setSearchTerm: (searchTerm: string) => {
        searchTerm: string
    }
    setSelectedCategories: (categories: string[]) => {
        categories: string[]
    }
    setSelectedTool: (tool: string | null) => {
        tool: string | null
    }
    setToolQualityPageIndex: (pageIndex: number) => {
        pageIndex: number
    }
    setToolQualitySort: (
        column: ToolQualitySortColumn,
        direction: SortDirection
    ) => {
        column: MCPToolQualitySortColumn
        direction: SortDirection
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface mcpAnalyticsToolQualityLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        dateRangeLabel: (dateFilter: DateFilter) => string
        intervalOptions: (dateFilter: DateFilter, timezone: string) => IntervalOption[]
        interval: (dateFilter: DateFilter, pinnedInterval: IntervalType | null, timezone: string) => IntervalType
        scopeShare: (categoryCounts: CategoryCount[], selectedCategories: string[]) => ScopeShare
        loadedToolQualityPageIndex: (toolRowsPage: ToolRowsPage | null) => number
        toolRows: (toolRowsPage: ToolRowsPage | null) => MCPToolQualityRowItem[]
        toolRowsTotalCount: (toolRowsPage: ToolRowsPage | null) => number
        toolRowsTotalSessions: (toolRowsPage: ToolRowsPage | null) => number
        toolRowsPreviousTotalSessions: (toolRowsPage: ToolRowsPage | null) => number
        dailyChartData: (
            dailyStats: DailyToolStat[],
            dateFilter: DateFilter,
            interval: IntervalType,
            timezone: string
        ) => DailyChartData
        incompleteTail: (dailyChartData: DailyChartData, interval: IntervalType, timezone: string) => boolean
        latencyBoxes: (dailyChartData: DailyChartData, incompleteTail: boolean) => (BoxPlotDatum | null)[]
    }
}

export type mcpAnalyticsToolQualityLogicType = MakeLogicType<
    mcpAnalyticsToolQualityLogicValues,
    mcpAnalyticsToolQualityLogicActions,
    Record<string, any>,
    mcpAnalyticsToolQualityLogicMeta
>

export const mcpAnalyticsToolQualityLogic = kea<mcpAnalyticsToolQualityLogicType>([
    path(['products', 'mcp_analytics', 'frontend', 'mcpAnalyticsToolQualityLogic']),

    connect(() => ({
        values: [mcpAnalyticsFiltersLogic, ['queryFilters as sharedQueryFilters']],
        actions: [mcpAnalyticsFiltersLogic, ['hydrateFilters', 'setFilterTestAccounts', 'setPropertyFilters']],
    })),

    actions({
        setToolQualitySort: (column: ToolQualitySortColumn, direction: SortDirection) => ({ column, direction }),
        setToolQualityPageIndex: (pageIndex: number) => ({ pageIndex }),
        setDateFilter: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
        setPinnedInterval: (interval: IntervalType | null) => ({ interval }),
        setSelectedCategories: (categories: string[]) => ({ categories }),
        setSelectedTool: (tool: string | null) => ({ tool }),
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        reloadAll: true,
        setChartView: (change: ChartViewChange) => change,
    }),

    reducers({
        chartViews: [
            DEFAULT_CHART_VIEWS,
            { persist: true },
            {
                setChartView: (state, { chart, view }): ChartViews => ({ ...state, [chart]: view }),
            },
        ],
        toolQualitySort: [
            DEFAULT_SORT,
            {
                setToolQualitySort: (_, { column, direction }): SortState => ({ column, direction }),
            },
        ],
        dateFilter: [
            DEFAULT_DATE_FILTER,
            {
                setDateFilter: (_, { dateFrom, dateTo }): DateFilter => ({ dateFrom, dateTo }),
            },
        ],
        // The grouping the user picked, kept independent of the window: null means follow the
        // auto-choice for the range. It survives date changes so switching windows doesn't quietly
        // undo the pin — `interval` drops back to auto only when the pin no longer fits.
        pinnedInterval: [
            null as IntervalType | null,
            {
                setPinnedInterval: (_, { interval }): IntervalType | null => interval,
            },
        ],
        selectedCategories: [
            [] as string[],
            {
                setSelectedCategories: (_, { categories }): string[] => categories,
            },
        ],
        selectedTool: [
            null as string | null,
            {
                setSelectedTool: (_, { tool }): string | null => tool,
            },
        ],
        searchTerm: [
            '',
            {
                setSearchTerm: (_, { searchTerm }): string => searchTerm,
            },
        ],
        toolQualityPageIndex: [
            0,
            {
                setToolQualityPageIndex: (_, { pageIndex }): number => Math.max(pageIndex, 0),
            },
        ],
    }),

    loaders(({ values }) => ({
        availableCategories: [
            [] as string[],
            {
                loadAvailableCategories: async (_: void, breakpoint): Promise<string[]> => {
                    // Fixed 30-day window so the scope selector lists every category regardless of the tab's
                    // date filter, though the shared property filters and test-account switch still narrow it.
                    const response = (await api.query({
                        kind: NodeKind.MCPToolCategoriesQuery,
                        dateRange: { date_from: '-30d' },
                        ...values.sharedQueryFilters,
                    })) as { results?: MCPToolCategoryItem[] }
                    breakpoint()
                    return (response.results ?? []).map((r) => r.category).filter(Boolean)
                },
            },
        ],
        categoryCounts: [
            [] as CategoryCount[],
            {
                loadCategoryCounts: async (_: void, breakpoint): Promise<CategoryCount[]> => {
                    const response = (await api.query({
                        kind: NodeKind.MCPToolCategoryCountsQuery,
                        dateRange: { date_from: values.dateFilter.dateFrom, date_to: values.dateFilter.dateTo },
                        ...values.sharedQueryFilters,
                    })) as { results?: MCPToolCategoryCountItem[] }
                    breakpoint()
                    return (response.results ?? []).map((r) => ({ category: r.category, calls: r.calls }))
                },
            },
        ],
        toolRowsPage: [
            null as ToolRowsPage | null,
            {
                loadToolRowsPage: async (_: void, breakpoint): Promise<ToolRowsPage> => {
                    await breakpoint(300)
                    const pageIndex = values.toolQualityPageIndex
                    const response = (await api.query({
                        kind: NodeKind.MCPToolQualityRowsQuery,
                        dateRange: { date_from: values.dateFilter.dateFrom, date_to: values.dateFilter.dateTo },
                        categories: values.selectedCategories,
                        search: values.searchTerm,
                        sortColumn: values.toolQualitySort.column,
                        sortDirection: values.toolQualitySort.direction,
                        limit: TOOL_QUALITY_PAGE_SIZE,
                        offset: pageIndex * TOOL_QUALITY_PAGE_SIZE,
                        ...values.sharedQueryFilters,
                    })) as MCPToolQualityRowsQueryResponse
                    breakpoint()
                    return { ...response, pageIndex }
                },
            },
        ],
        dailyStats: [
            [] as DailyToolStat[],
            {
                loadDailyStats: async (_: void, breakpoint): Promise<DailyToolStat[]> => {
                    await breakpoint(100)
                    const response = (await api.query({
                        kind: NodeKind.MCPToolQualityDailyStatsQuery,
                        dateRange: { date_from: values.dateFilter.dateFrom, date_to: values.dateFilter.dateTo },
                        interval: values.interval,
                        categories: values.selectedCategories,
                        ...(values.selectedTool ? { toolName: values.selectedTool } : {}),
                        ...values.sharedQueryFilters,
                    })) as { results?: MCPToolQualityDailyStatItem[] }
                    breakpoint()
                    return (response.results ?? []).map((r) => ({
                        day: r.day,
                        calls: r.calls,
                        errors: r.errors,
                        p50: r.p50,
                        p95: r.p95,
                        p99: r.p99,
                        min: r.min,
                        p25: r.p25,
                        mean: r.mean,
                        p75: r.p75,
                        max: r.max,
                    }))
                },
            },
        ],
    })),

    selectors({
        // Human-readable label for the active window (e.g. "Last 7 days"), used by
        // the scope-share headline so it never falls out of sync with the filter.
        dateRangeLabel: [
            (s) => [s.dateFilter],
            (dateFilter: DateFilter): string =>
                dateFilterToText(dateFilter.dateFrom, dateFilter.dateTo, 'the selected range') ?? 'the selected range',
        ],
        intervalOptions: [
            (s) => [s.dateFilter, teamLogic.selectors.timezone],
            (dateFilter: DateFilter, timezone: string): IntervalOption[] =>
                intervalOptionsForWindow(dateFilter.dateFrom, dateFilter.dateTo, timezone),
        ],
        // Grouping interval for the charts: the pinned choice, or PostHog's standard auto-choice when
        // none is pinned, so a sub-day window (e.g. last 12 hours) still buckets hourly by default
        // instead of collapsing to a single day point.
        interval: [
            (s) => [s.dateFilter, s.pinnedInterval, teamLogic.selectors.timezone],
            (dateFilter: DateFilter, pinnedInterval: IntervalType | null, timezone: string): IntervalType =>
                resolveInterval(dateFilter.dateFrom, dateFilter.dateTo, timezone, pinnedInterval),
        ],
        scopeShare: [
            (s) => [s.categoryCounts, s.selectedCategories],
            (categoryCounts: CategoryCount[], selectedCategories: string[]): ScopeShare => {
                const total = categoryCounts.reduce((acc, row) => acc + row.calls, 0)
                const selected = new Set(selectedCategories)
                const inScope = categoryCounts
                    .filter((row) => selected.has(row.category))
                    .reduce((acc, row) => acc + row.calls, 0)
                return { inScope, total, pct: total > 0 ? (inScope / total) * 100 : null }
            },
        ],
        loadedToolQualityPageIndex: [
            (s) => [s.toolRowsPage],
            (toolRowsPage: ToolRowsPage | null): number => toolRowsPage?.pageIndex ?? 0,
        ],
        toolRows: [
            (s) => [s.toolRowsPage],
            (toolRowsPage: ToolRowsPage | null): MCPToolQualityRowItem[] => toolRowsPage?.results ?? [],
        ],
        toolRowsTotalCount: [
            (s) => [s.toolRowsPage],
            (toolRowsPage: ToolRowsPage | null): number => toolRowsPage?.totalCount ?? 0,
        ],
        toolRowsTotalSessions: [
            (s) => [s.toolRowsPage],
            (toolRowsPage: ToolRowsPage | null): number => toolRowsPage?.totalSessions ?? 0,
        ],
        toolRowsPreviousTotalSessions: [
            (s) => [s.toolRowsPage],
            (toolRowsPage: ToolRowsPage | null): number => toolRowsPage?.previousTotalSessions ?? 0,
        ],
        dailyChartData: [
            (s) => [s.dailyStats, s.dateFilter, s.interval, teamLogic.selectors.timezone],
            (
                dailyStats: DailyToolStat[],
                dateFilter: DateFilter,
                interval: IntervalType,
                timezone: string
            ): DailyChartData => {
                const bucketKeys = buildBucketKeys(dateFilter.dateFrom, dateFilter.dateTo, timezone, interval)
                return buildDailyChartData(dailyStats, bucketKeys)
            },
        ],
        // The charts dash the final segment when it is the current, still-collecting interval, so a
        // partial day doesn't read as a fall in calls or a latency improvement.
        incompleteTail: [
            (s) => [s.dailyChartData, s.interval, teamLogic.selectors.timezone],
            (dailyChartData: DailyChartData, interval: IntervalType, timezone: string): boolean =>
                lastBucketIsInProgress(dailyChartData.labels, timezone, interval),
        ],
        latencyBoxes: [
            (s) => [s.dailyChartData, s.incompleteTail],
            (dailyChartData: DailyChartData, incompleteTail: boolean): (BoxPlotDatum | null)[] =>
                maskIncompleteLatencyBox(dailyChartData.latencyBoxes, incompleteTail),
        ],
    }),

    listeners(({ actions, values }) => {
        const loadFirstToolPage = (): void => {
            if (values.toolQualityPageIndex === 0) {
                actions.loadToolRowsPage()
            } else {
                actions.setToolQualityPageIndex(0)
            }
        }
        const loadUnscopedDailyStats = (): void => {
            if (values.selectedTool) {
                actions.setSelectedTool(null)
            } else {
                actions.loadDailyStats()
            }
        }

        return {
            setChartView: (change) => {
                posthog.capture('mcp analytics tool quality chart view changed', change)
            },
            setDateFilter: () => {
                loadFirstToolPage()
                loadUnscopedDailyStats()
                actions.loadCategoryCounts()
            },
            setFilterTestAccounts: () => {
                loadFirstToolPage()
                loadUnscopedDailyStats()
                actions.loadCategoryCounts()
                actions.loadAvailableCategories()
            },
            setPropertyFilters: () => {
                loadFirstToolPage()
                loadUnscopedDailyStats()
                actions.loadCategoryCounts()
                actions.loadAvailableCategories()
            },
            hydrateFilters: () => {
                loadFirstToolPage()
                loadUnscopedDailyStats()
                actions.loadCategoryCounts()
                actions.loadAvailableCategories()
            },
            setSelectedCategories: () => {
                loadFirstToolPage()
                loadUnscopedDailyStats()
            },
            setToolQualitySort: () => {
                loadFirstToolPage()
            },
            setSearchTerm: () => {
                loadFirstToolPage()
            },
            setToolQualityPageIndex: () => {
                actions.loadToolRowsPage()
            },
            setPinnedInterval: () => {
                actions.loadDailyStats()
            },
            reloadAll: () => {
                actions.loadToolRowsPage()
                actions.loadDailyStats()
                actions.loadCategoryCounts()
                actions.loadAvailableCategories()
            },
            setSelectedTool: () => {
                actions.loadDailyStats()
            },
            loadToolRowsPageSuccess: ({ toolRowsPage }) => {
                if (values.toolQualityPageIndex > 0 && toolRowsPage.results.length === 0) {
                    actions.setToolQualityPageIndex(0)
                }
            },
        }
    }),

    actionToUrl(({ values }) => {
        const syncUrl = (): [string, Record<string, any>, Record<string, any>, { replace: boolean }] => {
            const { currentLocation } = router.values
            const searchParams = { ...currentLocation.searchParams }
            if (values.selectedTool) {
                searchParams.tool = values.selectedTool
            } else {
                delete searchParams.tool
            }
            if (values.selectedCategories.length > 0) {
                searchParams.categories = values.selectedCategories
            } else {
                delete searchParams.categories
            }
            if (values.dateFilter.dateFrom) {
                searchParams.date_from = values.dateFilter.dateFrom
            } else {
                delete searchParams.date_from
            }
            if (values.dateFilter.dateTo) {
                searchParams.date_to = values.dateFilter.dateTo
            } else {
                delete searchParams.date_to
            }
            if (values.pinnedInterval) {
                searchParams.interval = values.pinnedInterval
            } else {
                delete searchParams.interval
            }
            return [currentLocation.pathname, searchParams, currentLocation.hashParams, { replace: true }]
        }
        return {
            setSelectedTool: syncUrl,
            setDateFilter: syncUrl,
            setPinnedInterval: syncUrl,
            setSelectedCategories: syncUrl,
        }
    }),

    urlToAction(({ actions, values }) => ({
        [urls.mcpAnalyticsToolQuality()]: (_, searchParams) => {
            const tool = typeof searchParams.tool === 'string' && searchParams.tool ? searchParams.tool : null
            if (tool !== values.selectedTool) {
                actions.setSelectedTool(tool)
            }
            const categories = Array.isArray(searchParams.categories)
                ? searchParams.categories.map(String)
                : typeof searchParams.categories === 'string' && searchParams.categories
                  ? [searchParams.categories]
                  : []
            if (JSON.stringify(categories) !== JSON.stringify(values.selectedCategories)) {
                actions.setSelectedCategories(categories)
            }
            const dateFrom =
                typeof searchParams.date_from === 'string' ? searchParams.date_from : values.dateFilter.dateFrom
            const dateTo = typeof searchParams.date_to === 'string' ? searchParams.date_to : null
            if (dateFrom !== values.dateFilter.dateFrom || dateTo !== values.dateFilter.dateTo) {
                actions.setDateFilter(dateFrom, dateTo)
            }
            const interval = parseIntervalParam(searchParams.interval)
            if (interval !== values.pinnedInterval) {
                actions.setPinnedInterval(interval)
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadAvailableCategories()
        actions.loadCategoryCounts()
        actions.loadToolRowsPage()
        actions.loadDailyStats()
    }),
])
