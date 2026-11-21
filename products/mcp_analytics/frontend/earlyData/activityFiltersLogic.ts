import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { hogql } from 'lib/utils/hogql'
import { urls } from 'scenes/urls'

import { DataTableNode } from '~/queries/schema/schema-general'

import {
    ACTIVITY_DEFAULT_DATE_FROM,
    MCP_TOOL_EXPR,
    activityDateFilter,
    withActivityWhere,
} from '../components/toolCallFeedQuery'
import { mcpAnalyticsFiltersLogic } from '../mcpAnalyticsFiltersLogic'
import type { DateFilter } from '../mcpAnalyticsToolQualityLogic'
import { mcpFacetsLogic } from '../mcpFacetsLogic'
import { mcpEarlyDataLogic } from './mcpEarlyDataLogic'

const SEARCH_DEBOUNCE_MS = 300

export function activityWhere(search: string): string[] {
    const term = search.trim()
    if (!term) {
        return []
    }
    const pattern = `%${term}%`
    const tool = hogql.raw(MCP_TOOL_EXPR)
    return [
        hogql`(${tool} ILIKE ${pattern} OR toString(properties.$mcp_intent) ILIKE ${pattern} OR toString(properties.$mcp_parameters) ILIKE ${pattern} OR toString(properties.$mcp_error_message) ILIKE ${pattern})`,
    ]
}

export const activityFiltersLogic = kea([
    path(['products', 'mcp_analytics', 'frontend', 'earlyData', 'activityFiltersLogic']),
    connect(() => ({
        values: [mcpEarlyDataLogic, ['activityQuery'], mcpFacetsLogic, ['facets']],
        actions: [
            mcpEarlyDataLogic,
            ['setActivityQuery', 'showFailedCallsOnly'],
            mcpAnalyticsFiltersLogic,
            ['setFacetFilters'],
        ],
    })),
    actions({
        setSearch: (search: string) => ({ search }),
        setDateRange: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
    }),
    reducers({
        search: ['', { setSearch: (_, { search }) => search }],
    }),
    selectors({
        dateRange: [
            (s) => [s.activityQuery],
            (activityQuery: DataTableNode): DateFilter => activityDateFilter(activityQuery),
        ],
    }),
    listeners(({ actions, values }) => ({
        setSearch: async ({ search }, breakpoint) => {
            await breakpoint(SEARCH_DEBOUNCE_MS)
            actions.setActivityQuery(withActivityWhere(values.activityQuery as DataTableNode, activityWhere(search)))
        },
        setDateRange: ({ dateFrom, dateTo }) => {
            const query = values.activityQuery as DataTableNode
            actions.setActivityQuery({
                ...query,
                source: { ...query.source, after: dateFrom ?? undefined, before: dateTo ?? undefined },
            } as DataTableNode)
        },
        // Every error type the window has seen, which narrows the feed to errored calls.
        showFailedCallsOnly: () =>
            actions.setFacetFilters({ errors: (values.facets?.errorTypes ?? []).map((option) => option.value) }),
    })),
    // The date range lives in the URL, like on the other tabs.
    actionToUrl(({ values }) => ({
        setDateRange: () => {
            const { currentLocation } = router.values
            const searchParams = { ...currentLocation.searchParams }
            for (const [key, value] of [
                ['date_from', values.dateRange.dateFrom],
                ['date_to', values.dateRange.dateTo],
            ] as const) {
                if (value) {
                    searchParams[key] = value
                } else {
                    delete searchParams[key]
                }
            }
            return [currentLocation.pathname, searchParams, currentLocation.hashParams, { replace: true }]
        },
    })),
    urlToAction(({ actions, values }) => ({
        [urls.mcpAnalyticsActivity()]: (_, searchParams) => {
            const dateFrom =
                typeof searchParams.date_from === 'string' ? searchParams.date_from : ACTIVITY_DEFAULT_DATE_FROM
            const dateTo = typeof searchParams.date_to === 'string' ? searchParams.date_to : null
            if (dateFrom !== values.dateRange.dateFrom || dateTo !== values.dateRange.dateTo) {
                actions.setDateRange(dateFrom, dateTo)
            }
        },
    })),
])
