import { actions, connect, kea, path, reducers, selectors } from 'kea'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { groupsModel } from '~/models/groupsModel'
import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'

import { SortDirection, SortState, llmAnalyticsSharedLogic } from '../llmAnalyticsSharedLogic'
import type { llmAnalyticsUsersLogicType } from './llmAnalyticsUsersLogicType'

export const llmAnalyticsUsersLogic = kea<llmAnalyticsUsersLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'tabs', 'llmAnalyticsUsersLogic']),
    connect({
        values: [
            llmAnalyticsSharedLogic,
            ['dateFilter', 'shouldFilterTestAccounts', 'propertyFilters'],
            groupsModel,
            ['groupsTaxonomicTypes'],
        ],
    }),

    actions({
        setUsersSort: (column: string, direction: SortDirection) => ({ column, direction }),
    }),

    reducers({
        usersSort: [
            { column: 'last_seen', direction: 'DESC' } as SortState,
            {
                setUsersSort: (_, { column, direction }): SortState => ({ column, direction }),
            },
        ],
    }),

    selectors({
        usersQuery: [
            (s) => [s.dateFilter, s.shouldFilterTestAccounts, s.propertyFilters, s.usersSort, s.groupsTaxonomicTypes],
            (
                dateFilter,
                shouldFilterTestAccounts,
                propertyFilters,
                usersSort,
                groupsTaxonomicTypes
            ): DataTableNode => ({
                kind: NodeKind.DataTableNode,
                source: {
                    kind: NodeKind.HogQLQuery,
                    query: `
                SELECT
                    argMax(user_tuple, timestamp) as user,
                    countDistinctIf(ai_trace_id, notEmpty(ai_trace_id)) as traces,
                    count() as generations,
                    countIf(notEmpty(ai_error) OR ai_is_error = 'true') as errors,
                    round(sum(toFloat(ai_total_cost_usd)), 4) as total_cost,
                    min(timestamp) as first_seen,
                    max(timestamp) as last_seen
                FROM (
                    SELECT
                        distinct_id,
                        timestamp,
                        JSONExtractRaw(properties, '$ai_trace_id') as ai_trace_id,
                        JSONExtractRaw(properties, '$ai_total_cost_usd') as ai_total_cost_usd,
                        JSONExtractRaw(properties, '$ai_error') as ai_error,
                        JSONExtractString(properties, '$ai_is_error') as ai_is_error,
                        tuple(
                            distinct_id,
                            person.created_at,
                            person.properties
                        ) as user_tuple
                    FROM events
                    WHERE event = '$ai_generation' AND {filters}
                )
                GROUP BY distinct_id
                ORDER BY ${usersSort.column} ${usersSort.direction}
                LIMIT 50
                    `,
                    filters: {
                        dateRange: {
                            date_from: dateFilter.dateFrom || null,
                            date_to: dateFilter.dateTo || null,
                        },
                        filterTestAccounts: shouldFilterTestAccounts,
                        properties: propertyFilters,
                    },
                },
                columns: ['user', 'traces', 'generations', 'errors', 'total_cost', 'first_seen', 'last_seen'],
                showDateRange: true,
                showReload: true,
                showSearch: true,
                showPropertyFilter: [
                    TaxonomicFilterGroupType.EventProperties,
                    TaxonomicFilterGroupType.PersonProperties,
                    ...groupsTaxonomicTypes,
                    TaxonomicFilterGroupType.Cohorts,
                    TaxonomicFilterGroupType.HogQLExpression,
                ],
                showTestAccountFilters: true,
                showExport: true,
                showColumnConfigurator: true,
                allowSorting: true,
            }),
        ],
    }),
])
