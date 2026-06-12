import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import api from 'lib/api'
import { urls } from 'scenes/urls'

import { hogqlQuery } from '~/queries/query'
import { HogQLQueryResponse, NodeKind } from '~/queries/schema/schema-general'
import { hogql } from '~/queries/utils'
import { type AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import toolQualityQueryTemplate from '../backend/templates/tool_quality.sql?raw'
import type { mcpAnalyticsToolQualityLogicType } from './mcpAnalyticsToolQualityLogicType'

// `$mcp_tool_category` is stamped onto every mcp_tool_call event by the producer
// (PostHog's MCP server from its catalog; external servers via the SDK). We read
// the available categories straight from the data so the scope selector works for
// any project's taxonomy without a hardcoded tool→category map.
const CATEGORIES_QUERY = hogql`
SELECT DISTINCT toString(properties.$mcp_tool_category) AS category
FROM events
WHERE event = 'mcp_tool_call'
    AND timestamp >= now() - INTERVAL 30 DAY
    AND properties.$mcp_tool_category IS NOT NULL
    AND properties.$mcp_tool_category != ''
ORDER BY category
`

// Per-category call counts over a fixed 7-day window powering the "share of MCP
// usage" headline. Rows with an empty category count toward the total but not the
// in-scope numerator, so uncategorized traffic dilutes the share as expected.
const CATEGORY_COUNTS_QUERY = hogql`
SELECT toString(properties.$mcp_tool_category) AS category, count() AS calls
FROM events
WHERE event = 'mcp_tool_call'
    AND timestamp >= now() - INTERVAL 7 DAY
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

// One row per tool from tool_quality.sql, parsed into a typed shape so the
// quill table and the selected-tool strip can render without re-querying.
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

// Pivoted per-day series feeding the three trend charts.
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

const EMPTY_CHART_DATA: DailyChartData = {
    labels: [],
    calls: [],
    errors: [],
    successRate: [],
    p50: [],
    p95: [],
    p99: [],
}

function escapeHogQLString(value: string): string {
    return value.replace(/\\/g, '\\\\').replace(/'/g, "\\'")
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
                    const response = await hogqlQuery(CATEGORY_COUNTS_QUERY)
                    return ((response?.results as unknown[][]) ?? []).map((r) => ({
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
                    const toolClause = values.selectedTool
                        ? `AND properties.$mcp_tool_name = '${escapeHogQLString(values.selectedTool)}'`
                        : ''
                    const response = (await api.query({
                        kind: NodeKind.HogQLQuery,
                        query: `
SELECT
    toDate(timestamp) AS day,
    count() AS calls,
    countIf(toBool(properties.$mcp_is_error)) AS errors,
    round(quantile(0.5)(toFloat(properties.$mcp_duration_ms))) AS p50,
    round(quantile(0.95)(toFloat(properties.$mcp_duration_ms))) AS p95,
    round(quantile(0.99)(toFloat(properties.$mcp_duration_ms))) AS p99
FROM events
WHERE event = 'mcp_tool_call'
    AND properties.$mcp_tool_name IS NOT NULL
    AND properties.$mcp_tool_name != ''
    ${toolClause}
    AND {filters}
GROUP BY day
ORDER BY day
`,
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
        toolOptions: [(s) => [s.toolRows], (toolRows: ToolQualityRow[]): string[] => toolRows.map((row) => row.tool)],
        selectedRow: [
            (s) => [s.toolRows, s.selectedTool],
            (toolRows: ToolQualityRow[], selectedTool: string | null): ToolQualityRow | null =>
                selectedTool ? (toolRows.find((row) => row.tool === selectedTool) ?? null) : null,
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
            (s) => [s.dailyStats],
            (dailyStats: DailyToolStat[]): DailyChartData => {
                if (dailyStats.length === 0) {
                    return EMPTY_CHART_DATA
                }
                return {
                    labels: dailyStats.map((r) => r.day),
                    calls: dailyStats.map((r) => r.calls),
                    errors: dailyStats.map((r) => r.errors),
                    successRate: dailyStats.map((r) => (r.calls ? ((r.calls - r.errors) / r.calls) * 100 : 0)),
                    p50: dailyStats.map((r) => r.p50),
                    p95: dailyStats.map((r) => r.p95),
                    p99: dailyStats.map((r) => r.p99),
                }
            },
        ],
    }),

    listeners(({ actions }) => ({
        setDateFilter: () => {
            actions.loadToolRows()
            actions.loadDailyStats()
        },
        setSelectedCategories: () => {
            actions.loadToolRows()
            actions.loadDailyStats()
        },
        setSelectedTool: () => {
            actions.loadDailyStats()
        },
    })),

    actionToUrl(({ values }) => ({
        setSelectedTool: () => {
            const { currentLocation } = router.values
            const searchParams = { ...currentLocation.searchParams }
            if (values.selectedTool) {
                searchParams.tool = values.selectedTool
            } else {
                delete searchParams.tool
            }
            return [currentLocation.pathname, searchParams, currentLocation.hashParams, { replace: true }]
        },
    })),

    urlToAction(({ actions, values }) => ({
        [urls.mcpAnalyticsToolQuality()]: (_, searchParams) => {
            const tool = typeof searchParams.tool === 'string' && searchParams.tool ? searchParams.tool : null
            if (tool !== values.selectedTool) {
                actions.setSelectedTool(tool)
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
