import { actions, connect, kea, path, reducers, selectors } from 'kea'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { groupsModel } from '~/models/groupsModel'
import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'
import { AnyPropertyFilter } from '~/types'

import toolsQueryTemplate from '../../backend/queries/tools.sql?raw'
import { SortDirection, SortState, llmAnalyticsSharedLogic } from '../llmAnalyticsSharedLogic'
import type { llmAnalyticsToolsLogicType } from './llmAnalyticsToolsLogicType'

export const llmAnalyticsToolsLogic = kea<llmAnalyticsToolsLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'tabs', 'llmAnalyticsToolsLogic']),
    connect(() => ({
        values: [
            llmAnalyticsSharedLogic,
            ['dateFilter', 'shouldFilterTestAccounts', 'propertyFilters'],
            groupsModel,
            ['groupsTaxonomicTypes'],
        ],
    })),

    actions({
        setToolsSort: (column: string, direction: SortDirection) => ({ column, direction }),
    }),

    reducers({
        toolsSort: [
            { column: 'total_calls', direction: 'DESC' } as SortState,
            {
                setToolsSort: (_, { column, direction }): SortState => ({ column, direction }),
            },
        ],
    }),

    selectors({
        toolsQuery: [
            (s) => [s.dateFilter, s.shouldFilterTestAccounts, s.propertyFilters, s.toolsSort, s.groupsTaxonomicTypes],
            (
                dateFilter: { dateFrom: string | null; dateTo: string | null },
                shouldFilterTestAccounts: boolean,
                propertyFilters: AnyPropertyFilter[],
                toolsSort: SortState,
                groupsTaxonomicTypes: TaxonomicFilterGroupType[]
            ): DataTableNode => {
                const query = toolsQueryTemplate
                    .replace('__ORDER_BY__', toolsSort.column)
                    .replace('__ORDER_DIRECTION__', toolsSort.direction)

                return {
                    kind: NodeKind.DataTableNode,
                    source: {
                        kind: NodeKind.HogQLQuery,
                        query,
                        filters: {
                            dateRange: {
                                date_from: dateFilter.dateFrom || null,
                                date_to: dateFilter.dateTo || null,
                            },
                            filterTestAccounts: shouldFilterTestAccounts,
                            properties: propertyFilters,
                        },
                    },
                    columns: [
                        'tool',
                        'total_calls',
                        'traces',
                        'users',
                        'sessions',
                        'days_seen',
                        'solo_pct',
                        'first_seen',
                        'last_seen',
                    ],
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
                }
            },
        ],
    }),
])
