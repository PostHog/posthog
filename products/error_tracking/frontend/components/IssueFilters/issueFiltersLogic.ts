import equal from 'fast-deep-equal'
import { actions, connect, kea, key, path, props, reducers, selectors } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { SelectedQuickFilter, quickFiltersSectionLogic } from 'lib/components/QuickFilters'
import { taxonomicFilterLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import { isUniversalGroupFilterLike } from 'lib/components/UniversalFilters/utils'
import { Params } from 'scenes/sceneTypes'

import { DateRange, QuickFilterContext } from '~/queries/schema/schema-general'
import { FilterLogicalOperator, PropertyFilterType, UniversalFiltersGroup } from '~/types'

import { syncSearchParams, updateSearchParams } from '../../utils'
import { TAXONOMIC_FILTER_LOGIC_KEY, TAXONOMIC_GROUP_TYPES } from './consts'
import type { issueFiltersLogicType } from './issueFiltersLogicType'

const DEFAULT_DATE_RANGE = { date_from: '-7d', date_to: null }
const DEFAULT_FILTER_GROUP = {
    type: FilterLogicalOperator.And,
    values: [{ type: FilterLogicalOperator.And, values: [] }],
}
const DEFAULT_TEST_ACCOUNT = false
const DEFAULT_SEARCH_QUERY = ''

export interface IssueFiltersLogicProps {
    logicKey: string
}

export const issueFiltersLogic = kea<issueFiltersLogicType>([
    path(['products', 'error_tracking', 'components', 'IssueFilters', 'issueFiltersLogic']),
    props({} as IssueFiltersLogicProps),
    key(({ logicKey }) => logicKey),

    connect(() => ({
        values: [
            quickFiltersSectionLogic({ context: QuickFilterContext.ErrorTrackingIssueFilters }),
            ['selectedQuickFilters'],
        ],
        actions: [
            taxonomicFilterLogic({
                taxonomicFilterLogicKey: TAXONOMIC_FILTER_LOGIC_KEY,
                taxonomicGroupTypes: TAXONOMIC_GROUP_TYPES,
            }),
            ['setSearchQuery as setTaxonomicSearchQuery'],
        ],
    })),

    actions({
        setDateRange: (dateRange: DateRange) => ({ dateRange }),
        setSearchQuery: (searchQuery: string) => ({ searchQuery }),
        setFilterGroup: (filterGroup: UniversalFiltersGroup) => ({ filterGroup }),
        setFilterTestAccounts: (filterTestAccounts: boolean) => ({ filterTestAccounts }),
    }),
    reducers({
        dateRange: [
            DEFAULT_DATE_RANGE as DateRange,
            { persist: true },
            {
                setDateRange: (_, { dateRange }) => dateRange,
            },
        ],
        filterGroup: [
            DEFAULT_FILTER_GROUP as UniversalFiltersGroup,
            { persist: true },
            {
                setFilterGroup: (_, { filterGroup }) => filterGroup,
            },
        ],
        filterTestAccounts: [
            DEFAULT_TEST_ACCOUNT as boolean,
            { persist: true },
            {
                setFilterTestAccounts: (_, { filterTestAccounts }) => filterTestAccounts,
            },
        ],
        searchQuery: [
            DEFAULT_SEARCH_QUERY as string,
            {
                setSearchQuery: (_, { searchQuery }) => searchQuery,
            },
        ],
    }),
    selectors({
        mergedFilterGroup: [
            (s) => [s.filterGroup, s.selectedQuickFilters],
            (
                filterGroup: UniversalFiltersGroup,
                selectedQuickFilters: Record<string, SelectedQuickFilter>
            ): UniversalFiltersGroup => {
                let omnisearchFilters: any[] = []
                if (
                    !!filterGroup.values &&
                    Array.isArray(filterGroup.values) &&
                    filterGroup.values.length > 0 &&
                    isUniversalGroupFilterLike(filterGroup.values[0])
                ) {
                    omnisearchFilters = filterGroup.values[0].values
                }

                const filtersFromQuickFilters = Object.values(selectedQuickFilters).map((qf: SelectedQuickFilter) => {
                    const filterValue = qf.value === null ? undefined : Array.isArray(qf.value) ? qf.value : [qf.value]

                    return {
                        type: PropertyFilterType.Event,
                        key: qf.propertyName,
                        operator: qf.operator,
                        ...(filterValue !== undefined && { value: filterValue }),
                    }
                })

                return {
                    type: FilterLogicalOperator.And,
                    values: [
                        {
                            type: FilterLogicalOperator.And,
                            values: [...omnisearchFilters, ...filtersFromQuickFilters],
                        },
                    ],
                } as UniversalFiltersGroup
            },
        ],
    }),

    urlToAction(({ actions, values }) => {
        const urlToAction = (_: any, params: Params): void => {
            if (params.dateRange && !equal(params.dateRange, values.dateRange)) {
                actions.setDateRange(params.dateRange)
            }
            if (params.filterGroup && !equal(params.filterGroup, values.filterGroup)) {
                actions.setFilterGroup(params.filterGroup)
            }
            if (params.filterTestAccounts && !equal(params.filterTestAccounts, values.filterTestAccounts)) {
                actions.setFilterTestAccounts(params.filterTestAccounts)
            }
            const newQuery = params.searchQuery ? params.searchQuery.toString() : null
            if (newQuery && !equal(newQuery, values.searchQuery)) {
                actions.setSearchQuery(newQuery)
                actions.setTaxonomicSearchQuery(newQuery)
            }
        }
        return {
            '*': urlToAction,
        }
    }),

    actionToUrl(({ values }) => {
        const buildURL = (): [
            string,
            Params,
            Record<string, any>,
            {
                replace: boolean
            },
        ] => {
            return syncSearchParams(router, (params: Params) => {
                updateSearchParams(params, 'filterTestAccounts', values.filterTestAccounts, DEFAULT_TEST_ACCOUNT)
                updateSearchParams(params, 'searchQuery', values.searchQuery, DEFAULT_SEARCH_QUERY)
                updateSearchParams(params, 'filterGroup', values.filterGroup, DEFAULT_FILTER_GROUP)
                updateSearchParams(params, 'dateRange', values.dateRange, DEFAULT_DATE_RANGE)
                return params
            })
        }

        return {
            setDateRange: () => buildURL(),
            setFilterGroup: () => buildURL(),
            setSearchQuery: () => buildURL(),
            setFilterTestAccounts: () => buildURL(),
        }
    }),
])
