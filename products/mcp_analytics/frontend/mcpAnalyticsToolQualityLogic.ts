import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, combineUrl, router, urlToAction } from 'kea-router'

import api from 'lib/api'
import { dateFilterToText, getDefaultInterval } from 'lib/utils/dateFilters'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { hogqlQuery } from '~/queries/query'
import { HogQLQueryResponse, NodeKind } from '~/queries/schema/schema-general'
import { hogql } from '~/queries/utils'
import { type AnyPropertyFilter, IntervalType, PropertyFilterType, PropertyOperator } from '~/types'

import toolQualityQueryTemplate from '../backend/templates/tool_quality.sql?raw'
import type { mcpAnalyticsToolQualityLogicType } from './mcpAnalyticsToolQualityLogicType'
import { buildBucketKeys, normalizeBucket } from './timeBuckets'

// `$mcp_tool_category` is stamped onto every $mcp_tool_call event by the producer
// (PostHog's MCP server from its catalog; external servers via the SDK). We read
// the available categories straight from the data so the scope selector works for
// any project's taxonomy without a hardcoded tool→category map.
const CATEGORIES_QUERY = hogql`
SELECT DISTINCT toString(properties.$mcp_tool_category) AS category
FROM events
WHERE event = '$mcp_tool_call'
    AND timestamp >= now() - INTERVAL 30 DAY
    AND properties.$mcp_tool_category IS NOT NULL
    AND properties.$mcp_tool_category != ''
ORDER BY category
`

// Per-category call counts over the selected window, powering the "share of MCP
// usage" headline. Rows with an empty category count toward the total but not the
// in-scope numerator, so uncategorized traffic dilutes the share as expected. The
// date range rides in via the {filters} placeholder so the headline tracks the
// same window as the rest of the tab.
const CATEGORY_COUNTS_QUERY = `
SELECT toString(properties.$mcp_tool_category) AS category, count() AS calls
FROM events
WHERE event = '$mcp_tool_call'
    AND {filters}
GROUP BY category
`

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
    column: string
    direction: SortDirection
}

export interface DateFilter {
    dateFrom: string | null
    dateTo: string | null
}

// Carry the selected window across navigation as date_from / date_to, mirroring the tab's
// actionToUrl. Only set them when present so a cleared range stays out of the URL.
export function mcpDateSearchParams(dateFilter: DateFilter): Record<string, string> {
    const params: Record<string, string> = {}
    if (dateFilter.dateFrom) {
        params.date_from = dateFilter.dateFrom
    }
    if (dateFilter.dateTo) {
        params.date_to = dateFilter.dateTo
    }
    return params
}

// Link from the Tool quality tab to an individual tool's report, keeping the date filter so
// the tool page opens on the same window.
export function mcpToolReportUrl(tool: string, dateFilter: DateFilter): string {
    return combineUrl(urls.mcpAnalyticsTool(tool), mcpDateSearchParams(dateFilter)).url
}

// Link back from a tool report to the Tool quality tab, restoring the date filter.
export function mcpToolQualityUrlWithDates(dateFilter: DateFilter): string {
    return combineUrl(urls.mcpAnalyticsToolQuality(), mcpDateSearchParams(dateFilter)).url
}

export interface ToolQualityRow {
    tool: string
    total_calls: number
    errors: number
    error_rate_pct: number
    p50_duration_ms: number
    p95_duration_ms: number
    p99_duration_ms: number
    users: number
    sessions: number
    first_seen: string
    last_seen: string
}

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
    successRate: number[]
    p50: number[]
    p95: number[]
    p99: number[]
}

const DEFAULT_DATE_FILTER: DateFilter = { dateFrom: '-7d', dateTo: null }
const DEFAULT_SORT: SortState = { column: 'total_calls', direction: 'DESC' }

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
        successRate: rows.map((r) => (r && r.calls ? ((r.calls - r.errors) / r.calls) * 100 : NaN)),
        p50: rows.map((r) => (r ? r.p50 : NaN)),
        p95: rows.map((r) => (r ? r.p95 : NaN)),
        p99: rows.map((r) => (r ? r.p99 : NaN)),
    }
}

function sortToolRows(rows: ToolQualityRow[], sort: SortState): ToolQualityRow[] {
    const direction = sort.direction === 'ASC' ? 1 : -1
    const column = sort.column as keyof ToolQualityRow
    return [...rows].sort((a, b) => {
        const aValue = a[column]
        const bValue = b[column]
        if (typeof aValue === 'number' && typeof bValue === 'number') {
            return (aValue - bValue) * direction
        }
        return String(aValue).localeCompare(String(bValue)) * direction
    })
}

export const mcpAnalyticsToolQualityLogic = kea<mcpAnalyticsToolQualityLogicType>([
    path(['products', 'mcp_analytics', 'frontend', 'mcpAnalyticsToolQualityLogic']),

    actions({
        setToolQualitySort: (column: string, direction: SortDirection) => ({ column, direction }),
        setDateFilter: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
        setSelectedCategories: (categories: string[]) => ({ categories }),
        setSelectedTool: (tool: string | null) => ({ tool }),
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        reloadAll: true,
    }),

    reducers({
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
    }),

    loaders(({ values }) => ({
        availableCategories: [
            [] as string[],
            {
                loadAvailableCategories: async (): Promise<string[]> => {
                    const response = await hogqlQuery(CATEGORIES_QUERY)
                    return ((response?.results as unknown[][]) ?? []).map((r) => String(r[0] ?? '')).filter(Boolean)
                },
            },
        ],
        categoryCounts: [
            [] as CategoryCount[],
            {
                loadCategoryCounts: async (): Promise<CategoryCount[]> => {
                    const response = (await api.query({
                        kind: NodeKind.HogQLQuery,
                        query: CATEGORY_COUNTS_QUERY,
                        filters: {
                            dateRange: {
                                date_from: values.dateFilter.dateFrom,
                                date_to: values.dateFilter.dateTo,
                            },
                        },
                    })) as HogQLQueryResponse
                    return ((response.results as unknown[][]) ?? []).map((r) => ({
                        category: String(r[0] ?? ''),
                        calls: Number(r[1] ?? 0),
                    }))
                },
            },
        ],
        toolRows: [
            [] as ToolQualityRow[],
            {
                loadToolRows: async (_: void, breakpoint): Promise<ToolQualityRow[]> => {
                    await breakpoint(100)
                    // Fixed server-side order; column sorting happens client-side on the loaded set.
                    const query = toolQualityQueryTemplate
                        .replace('__ORDER_BY__', 'total_calls')
                        .replace('__ORDER_DIRECTION__', 'DESC')
                    const response = (await api.query({
                        kind: NodeKind.HogQLQuery,
                        query,
                        filters: {
                            dateRange: {
                                date_from: values.dateFilter.dateFrom,
                                date_to: values.dateFilter.dateTo,
                            },
                            ...(values.categoryProperties.length > 0 ? { properties: values.categoryProperties } : {}),
                        },
                    })) as HogQLQueryResponse
                    breakpoint()
                    return ((response.results as unknown[][]) ?? []).map((r) => ({
                        tool: String(r[0] ?? ''),
                        total_calls: Number(r[1] ?? 0),
                        errors: Number(r[2] ?? 0),
                        error_rate_pct: Number(r[3] ?? 0),
                        p50_duration_ms: Number(r[4] ?? 0),
                        p95_duration_ms: Number(r[5] ?? 0),
                        p99_duration_ms: Number(r[6] ?? 0),
                        users: Number(r[7] ?? 0),
                        sessions: Number(r[8] ?? 0),
                        first_seen: String(r[9] ?? ''),
                        last_seen: String(r[10] ?? ''),
                    }))
                },
            },
        ],
        dailyStats: [
            [] as DailyToolStat[],
            {
                loadDailyStats: async (_: void, breakpoint): Promise<DailyToolStat[]> => {
                    await breakpoint(100)
                    // The selected tool rides along as a property filter resolved by the
                    // {filters} placeholder, so the value never touches the query string.
                    const toolProperty: AnyPropertyFilter[] = values.selectedTool
                        ? [
                              {
                                  key: '$mcp_tool_name',
                                  value: [values.selectedTool],
                                  operator: PropertyOperator.Exact,
                                  type: PropertyFilterType.Event,
                              },
                          ]
                        : []
                    const properties = [...values.categoryProperties, ...toolProperty]
                    const response = (await api.query({
                        kind: NodeKind.HogQLQuery,
                        // `values.interval` is a fixed IntervalType from getDefaultInterval, never user
                        // input, so interpolating it into the dateTrunc is safe.
                        query: `
SELECT
    dateTrunc('${values.interval}', timestamp) AS day,
    count() AS calls,
    countIf(toBool(properties.$mcp_is_error)) AS errors,
    round(quantile(0.5)(toFloat(properties.$mcp_duration_ms))) AS p50,
    round(quantile(0.95)(toFloat(properties.$mcp_duration_ms))) AS p95,
    round(quantile(0.99)(toFloat(properties.$mcp_duration_ms))) AS p99
FROM events
WHERE event = '$mcp_tool_call'
    AND properties.$mcp_tool_name IS NOT NULL
    AND properties.$mcp_tool_name != ''
    AND {filters}
GROUP BY day
ORDER BY day
`,
                        filters: {
                            dateRange: {
                                date_from: values.dateFilter.dateFrom,
                                date_to: values.dateFilter.dateTo,
                            },
                            ...(properties.length > 0 ? { properties } : {}),
                        },
                    })) as HogQLQueryResponse
                    breakpoint()
                    return ((response.results as unknown[][]) ?? []).map((r) => ({
                        day: String(r[0] ?? ''),
                        calls: Number(r[1] ?? 0),
                        errors: Number(r[2] ?? 0),
                        p50: Number(r[3] ?? 0),
                        p95: Number(r[4] ?? 0),
                        p99: Number(r[5] ?? 0),
                    }))
                },
            },
        ],
    })),

    selectors({
        // Event property filter applied to every query so the whole tab scopes to
        // the selected categories. Empty selection means "all categories".
        categoryProperties: [
            (s) => [s.selectedCategories],
            (selectedCategories: string[]): AnyPropertyFilter[] =>
                selectedCategories.length > 0
                    ? [
                          {
                              key: '$mcp_tool_category',
                              value: selectedCategories,
                              operator: PropertyOperator.Exact,
                              type: PropertyFilterType.Event,
                          },
                      ]
                    : [],
        ],
        // Human-readable label for the active window (e.g. "Last 7 days"), used by
        // the scope-share headline so it never falls out of sync with the filter.
        dateRangeLabel: [
            (s) => [s.dateFilter],
            (dateFilter: DateFilter): string =>
                dateFilterToText(dateFilter.dateFrom, dateFilter.dateTo, 'the selected range') ?? 'the selected range',
        ],
        // Grouping interval for the daily chart — PostHog's standard auto-choice, so a sub-day window
        // (e.g. last 12 hours) buckets hourly instead of collapsing to a single day point.
        interval: [
            (s) => [s.dateFilter],
            (dateFilter: DateFilter): IntervalType => getDefaultInterval(dateFilter.dateFrom, dateFilter.dateTo),
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
        filteredRows: [
            (s) => [s.toolRows, s.toolQualitySort, s.searchTerm],
            (toolRows: ToolQualityRow[], sort: SortState, searchTerm: string): ToolQualityRow[] => {
                const term = searchTerm.trim().toLowerCase()
                const filtered = term ? toolRows.filter((row) => row.tool.toLowerCase().includes(term)) : toolRows
                return sortToolRows(filtered, sort)
            },
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
    }),

    listeners(({ actions, values }) => ({
        // Both scope filters refetch the table and the charts; a date change also
        // refreshes the category counts so the "share of MCP usage" headline tracks
        // the same window.
        setDateFilter: () => {
            actions.reloadAll()
            actions.loadCategoryCounts()
        },
        setSelectedCategories: () => {
            actions.reloadAll()
        },
        reloadAll: () => {
            actions.loadToolRows()
            actions.loadDailyStats()
        },
        setSelectedTool: () => {
            actions.loadDailyStats()
        },
        // A category or date change can reload rows that no longer include the
        // selected tool — drop the selection instead of charting an empty scope
        loadToolRowsSuccess: ({ toolRows }) => {
            if (values.selectedTool && !toolRows.some((row) => row.tool === values.selectedTool)) {
                actions.setSelectedTool(null)
            }
        },
    })),

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
            return [currentLocation.pathname, searchParams, currentLocation.hashParams, { replace: true }]
        }
        return {
            setSelectedTool: syncUrl,
            setDateFilter: syncUrl,
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
        },
    })),

    afterMount(({ actions }) => {
        actions.loadAvailableCategories()
        actions.loadCategoryCounts()
        actions.loadToolRows()
        actions.loadDailyStats()
    }),
])
