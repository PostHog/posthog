import { actions, afterMount, connect, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'

import api from 'lib/api'

import { MCPMissingCapabilitiesItem, NodeKind } from '~/queries/schema/schema-general'
import { AnyPropertyFilter } from '~/types'

import { McpFacetFilters, mcpAnalyticsFiltersLogic } from '../mcpAnalyticsFiltersLogic'
import type { DateFilter } from '../mcpAnalyticsToolQualityLogic'
import { mcpDashboardOverviewLogic } from '../mcpDashboardOverviewLogic'
import { reportProperties } from '../missingCapabilities/mcpMissingCapabilitiesLogic'

const SUGGESTED_FIXES_SHOWN = 5

export const dashboardSuggestedFixesLogic = kea([
    path(['products', 'mcp_analytics', 'frontend', 'leaderboardHome', 'dashboardSuggestedFixesLogic']),
    connect(() => ({
        values: [
            mcpDashboardOverviewLogic,
            ['dateFilter'],
            mcpAnalyticsFiltersLogic,
            ['filterTestAccounts', 'propertyFilters', 'facetFilters'],
        ],
    })),
    actions({
        openFix: (fix: MCPMissingCapabilitiesItem | null) => ({ fix }),
    }),
    selectors({
        // A string, so it changes only when the filters behind the list do and drives a single reload.
        queryKey: [
            (s) => [s.dateFilter, s.filterTestAccounts, s.propertyFilters, s.facetFilters],
            (
                dateFilter: DateFilter,
                filterTestAccounts: boolean,
                propertyFilters: AnyPropertyFilter[],
                facetFilters: McpFacetFilters
            ): string =>
                JSON.stringify({
                    dateRange: { date_from: dateFilter.dateFrom, date_to: dateFilter.dateTo },
                    filterTestAccounts,
                    properties: reportProperties(propertyFilters, facetFilters, true),
                }),
        ],
    }),
    loaders(({ values }) => ({
        suggestedFixes: [
            [] as MCPMissingCapabilitiesItem[],
            {
                loadSuggestedFixes: async (_: void, breakpoint) => {
                    const response = (await api.query({
                        kind: NodeKind.MCPMissingCapabilitiesQuery,
                        ...JSON.parse(values.queryKey),
                        limit: SUGGESTED_FIXES_SHOWN,
                        offset: 0,
                    })) as { results?: MCPMissingCapabilitiesItem[] }
                    breakpoint()
                    return response.results ?? []
                },
            },
        ],
    })),
    reducers({
        openedFix: [
            null as MCPMissingCapabilitiesItem | null,
            {
                openFix: (_, { fix }) => fix,
                loadSuggestedFixes: () => null,
            },
        ],
        suggestedFixesFailed: [
            false,
            {
                loadSuggestedFixes: () => false,
                loadSuggestedFixesFailure: () => true,
            },
        ],
    }),
    subscriptions(({ actions }) => ({
        queryKey: (_: string, previous: string | undefined) => {
            if (previous !== undefined) {
                actions.loadSuggestedFixes()
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadSuggestedFixes()
    }),
])
