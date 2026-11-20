import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, combineUrl, router, urlToAction } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'
import posthog from 'posthog-js'

import api from 'lib/api'
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
    MCPToolQualityDailyStatItem,
    MCPToolQualityRowItem,
    MCPToolQualityRowsQueryResponse,
    MCPToolQualitySortColumn,
    MCPToolQualityTotals,
    NodeKind,
} from '~/queries/schema/schema-general'
import { IntervalType } from '~/types'

import type { MCPDetailDrawerPosition } from './components/MCPDetailDrawer'
import {
    type MCPSharedQueryFilters,
    mcpAnalyticsFiltersLogic,
    writeSharedFilterParams,
} from './mcpAnalyticsFiltersLogic'

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

// Link to the Tool quality tab that restores the date filter, the interval and, optionally, a table sort.
export function mcpToolQualityUrlWithDates(
    dateFilter: DateFilter,
    interval?: IntervalType | null,
    sort?: SortState
): string {
    return combineUrl(urls.mcpAnalyticsToolQuality(), {
        ...mcpToolNavigationParams(dateFilter, interval),
        ...(sort ? sortSearchParams(sort) : {}),
    }).url
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
}

export const TOOL_QUALITY_DEFAULT_DATE_FILTER: DateFilter = { dateFrom: '-7d', dateTo: null }
const DEFAULT_SORT: SortState = { column: 'total_calls', direction: 'DESC' }

// A Record so a new sort column fails to compile until the URL parser accepts it.
const SORT_COLUMNS: Record<ToolQualitySortColumn, true> = {
    total_calls: true,
    error_rate_pct: true,
    p50_duration_ms: true,
    p95_duration_ms: true,
    p99_duration_ms: true,
    users: true,
    sessions: true,
    last_seen: true,
    trend_score: true,
}

function isDefaultSort(sort: SortState): boolean {
    return sort.column === DEFAULT_SORT.column && sort.direction === DEFAULT_SORT.direction
}

// pinned: `sort` and `sort_direction` URL params. The dashboard's slowest-tools card links to them.
export function sortSearchParams(sort: SortState): Record<string, string> {
    return isDefaultSort(sort) ? {} : { sort: sort.column, sort_direction: sort.direction }
}

function parseSortParams(searchParams: Record<string, any>): SortState {
    const { sort, sort_direction } = searchParams
    if (typeof sort !== 'string' || !Object.hasOwn(SORT_COLUMNS, sort)) {
        return DEFAULT_SORT
    }
    return { column: sort as ToolQualitySortColumn, direction: sort_direction === 'ASC' ? 'ASC' : 'DESC' }
}
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
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface mcpAnalyticsToolQualityLogicValues {
    sharedQueryFilters: MCPSharedQueryFilters // mcpAnalyticsFiltersLogic
    dailyChartData: DailyChartData
    dailyStats: DailyToolStat[]
    dailyStatsLoading: boolean
    dateFilter: DateFilter
    incompleteTail: boolean
    interval: IntervalType
    intervalOptions: IntervalOption[]
    loadedToolQualityPageIndex: number
    nextTool: string | null
    pinnedInterval: IntervalType | null
    previousTool: string | null
    searchTerm: string
    selectedTool: string | null
    selectedToolPosition: MCPDetailDrawerPosition | null
    toolQualityPageIndex: number
    toolQualitySort: SortState
    toolRows: MCPToolQualityRowItem[]
    toolRowsLoadFailed: boolean
    toolRowsPage: ToolRowsPage | null
    toolRowsPageLoading: boolean
    toolRowsPreviousTotalSessions: number
    toolRowsTotalCount: number
    toolRowsTotalSessions: number
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface mcpAnalyticsToolQualityLogicActions {
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
    openToolDrawer: (tool: string) => {
        tool: string
    }
    reloadAll: () => {
        value: true
    }
    reloadForSharedFilters: () => {
        value: true
    }
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
        selectedToolPosition: (
            toolRows: MCPToolQualityRowItem[],
            selectedTool: string | null
        ) => MCPDetailDrawerPosition | null
        previousTool: (toolRows: MCPToolQualityRowItem[], selectedToolPosition: any) => string | null
        nextTool: (toolRows: MCPToolQualityRowItem[], selectedToolPosition: any) => string | null
        intervalOptions: (dateFilter: DateFilter, timezone: string) => IntervalOption[]
        interval: (dateFilter: DateFilter, pinnedInterval: IntervalType | null, timezone: string) => IntervalType
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
    })),

    actions({
        setToolQualitySort: (column: ToolQualitySortColumn, direction: SortDirection) => ({ column, direction }),
        setToolQualityPageIndex: (pageIndex: number) => ({ pageIndex }),
        setDateFilter: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
        setPinnedInterval: (interval: IntervalType | null) => ({ interval }),
        setSelectedTool: (tool: string | null) => ({ tool }),
        openToolDrawer: (tool: string) => ({ tool }),
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        setDailyTotals: (totals: MCPToolQualityTotals | null) => ({ totals }),
        reloadAll: true,
        reloadForSharedFilters: true,
    }),

    reducers({
        toolQualitySort: [
            DEFAULT_SORT,
            {
                setToolQualitySort: (_, { column, direction }): SortState => ({ column, direction }),
            },
        ],
        dateFilter: [
            TOOL_QUALITY_DEFAULT_DATE_FILTER,
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
        dailyTotals: [
            null as MCPToolQualityTotals | null,
            {
                setDailyTotals: (_, { totals }): MCPToolQualityTotals | null => totals,
            },
        ],
        toolQualityPageIndex: [
            0,
            {
                setToolQualityPageIndex: (_, { pageIndex }): number => Math.max(pageIndex, 0),
            },
        ],
    }),

    loaders(({ values, actions }) => ({
        toolRowsPage: [
            null as ToolRowsPage | null,
            {
                loadToolRowsPage: async (_: void, breakpoint): Promise<ToolRowsPage> => {
                    await breakpoint(300)
                    const pageIndex = values.toolQualityPageIndex
                    const response = (await api
                        .query({
                            kind: NodeKind.MCPToolQualityRowsQuery,
                            dateRange: { date_from: values.dateFilter.dateFrom, date_to: values.dateFilter.dateTo },
                            search: values.searchTerm,
                            interval: values.interval,
                            sortColumn: values.toolQualitySort.column,
                            sortDirection: values.toolQualitySort.direction,
                            limit: TOOL_QUALITY_PAGE_SIZE,
                            offset: pageIndex * TOOL_QUALITY_PAGE_SIZE,
                            ...values.sharedQueryFilters,
                        })
                        // kea-loaders dispatches a failure even from a request a newer one replaced.
                        .catch((error) => {
                            breakpoint()
                            throw error
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
                        includeTotals: true,
                        search: values.searchTerm,
                        ...values.sharedQueryFilters,
                    })) as { results?: MCPToolQualityDailyStatItem[]; totals?: MCPToolQualityTotals }
                    breakpoint()
                    actions.setDailyTotals(response.totals ?? null)
                    return (response.results ?? []).map((r) => ({
                        day: r.day,
                        calls: r.calls,
                        errors: r.errors,
                        p50: r.p50,
                        p95: r.p95,
                        p99: r.p99,
                    }))
                },
            },
        ],
    })),

    reducers({
        // A failed request drops the rows on screen, because they answered an earlier filter or page.
        toolRowsPage: {
            loadToolRowsPageFailure: (): ToolRowsPage | null => null,
        },
        toolRowsLoadFailed: [
            false,
            {
                loadToolRowsPage: () => false,
                loadToolRowsPageFailure: () => true,
            },
        ],
    }),

    selectors({
        selectedToolPosition: [
            (s) => [s.toolRows, s.selectedTool],
            (toolRows: MCPToolQualityRowItem[], selectedTool: string | null): MCPDetailDrawerPosition | null => {
                const index = selectedTool ? toolRows.findIndex((row) => row.tool === selectedTool) : -1
                return index >= 0 ? { index, total: toolRows.length } : null
            },
        ],
        previousTool: [
            (s) => [s.toolRows, s.selectedToolPosition],
            (toolRows: MCPToolQualityRowItem[], position: MCPDetailDrawerPosition | null): string | null =>
                position && position.index > 0 ? toolRows[position.index - 1].tool : null,
        ],
        nextTool: [
            (s) => [s.toolRows, s.selectedToolPosition],
            (toolRows: MCPToolQualityRowItem[], position: MCPDetailDrawerPosition | null): string | null =>
                position && position.index < toolRows.length - 1 ? toolRows[position.index + 1].tool : null,
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
    }),

    listeners(({ actions, values }) => {
        const loadFirstToolPage = (): void => {
            if (values.toolQualityPageIndex === 0) {
                actions.loadToolRowsPage()
            } else {
                actions.setToolQualityPageIndex(0)
            }
        }

        return {
            openToolDrawer: ({ tool }) => {
                posthog.capture('mcp analytics drawer opened', { list: 'tool quality' })
                actions.setSelectedTool(tool)
            },
            setDateFilter: () => {
                loadFirstToolPage()
                actions.loadDailyStats()
            },
            reloadForSharedFilters: () => {
                loadFirstToolPage()
                actions.loadDailyStats()
            },
            setToolQualitySort: () => {
                loadFirstToolPage()
            },
            setSearchTerm: () => {
                loadFirstToolPage()
                actions.loadDailyStats()
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
            },
            loadToolRowsPageSuccess: ({ toolRowsPage }) => {
                if (values.toolQualityPageIndex > 0 && toolRowsPage.results.length === 0) {
                    actions.setToolQualityPageIndex(0)
                }
            },
        }
    }),

    // The shared filters change from the filter bar, URL hydration, or the team's test-account default,
    // so react to the value rather than to any one action.
    subscriptions(({ actions }) => ({
        sharedQueryFilters: (_: MCPSharedQueryFilters, previous: MCPSharedQueryFilters | undefined) => {
            if (previous) {
                actions.reloadForSharedFilters()
            }
        },
    })),

    actionToUrl(({ values }) => {
        const syncUrl = (): [string, Record<string, any>, Record<string, any>, { replace: boolean }] => {
            const { currentLocation } = router.values
            const searchParams = { ...currentLocation.searchParams }
            // The open drawer stays out of the URL, so landing on the tab never reopens a tool.
            delete searchParams.tool
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
            // A shared filter change clears the selected tool before the filter logic writes its own URL params.
            writeSharedFilterParams(searchParams, mcpAnalyticsFiltersLogic.values)
            delete searchParams.sort
            delete searchParams.sort_direction
            Object.assign(searchParams, sortSearchParams(values.toolQualitySort))
            return [currentLocation.pathname, searchParams, currentLocation.hashParams, { replace: true }]
        }
        return {
            setDateFilter: syncUrl,
            setPinnedInterval: syncUrl,
            setToolQualitySort: syncUrl,
        }
    }),

    urlToAction(({ actions, values }) => ({
        [urls.mcpAnalyticsToolQuality()]: (_, searchParams) => {
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
            const sort = parseSortParams(searchParams)
            if (sort.column !== values.toolQualitySort.column || sort.direction !== values.toolQualitySort.direction) {
                actions.setToolQualitySort(sort.column, sort.direction)
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadToolRowsPage()
        actions.loadDailyStats()
    }),
])
