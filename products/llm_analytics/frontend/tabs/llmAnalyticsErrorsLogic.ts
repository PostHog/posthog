import { actions, connect, kea, path, reducers, selectors } from 'kea'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { groupsModel } from '~/models/groupsModel'
import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'
import { AnyPropertyFilter } from '~/types'

import errorsQueryTemplate from '../../backend/queries/errors.sql?raw'
import { SortDirection, SortState, llmAnalyticsSharedLogic } from '../llmAnalyticsSharedLogic'
import type { llmAnalyticsErrorsLogicType } from './llmAnalyticsErrorsLogicType'

export const llmAnalyticsErrorsLogic = kea<llmAnalyticsErrorsLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'tabs', 'llmAnalyticsErrorsLogic']),
    connect({
        values: [
            llmAnalyticsSharedLogic,
            ['dateFilter', 'shouldFilterTestAccounts', 'propertyFilters'],
            groupsModel,
            ['groupsTaxonomicTypes'],
        ],
    }),

    actions({
        setErrorsSort: (column: string, direction: SortDirection) => ({ column, direction }),
    }),

    reducers({
        errorsSort: [
            { column: 'traces', direction: 'DESC' } as SortState,
            {
                setErrorsSort: (_, { column, direction }): SortState => ({ column, direction }),
            },
        ],
    }),

    selectors({
        errorsQuery: [
            (s) => [s.dateFilter, s.shouldFilterTestAccounts, s.propertyFilters, s.errorsSort, s.groupsTaxonomicTypes],
            (
                dateFilter: { dateFrom: string | null; dateTo: string | null },
                shouldFilterTestAccounts: boolean,
                propertyFilters: AnyPropertyFilter[],
                errorsSort: SortState,
                groupsTaxonomicTypes: TaxonomicFilterGroupType[]
            ): DataTableNode => {
                // Use the shared query template
                // Simple placeholder replacement - no escaping needed
                const query = errorsQueryTemplate
                    .replace('__ORDER_BY__', errorsSort.column)
                    .replace('__ORDER_DIRECTION__', errorsSort.direction)

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
                        'error',
                        'traces',
                        'generations',
                        'spans',
                        'embeddings',
                        'sessions',
                        'users',
                        'days_seen',
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
