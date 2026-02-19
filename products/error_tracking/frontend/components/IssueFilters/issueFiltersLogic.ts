import equal from 'fast-deep-equal'
import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import { SelectedQuickFilter, quickFiltersSectionLogic } from 'lib/components/QuickFilters'
import { taxonomicFilterLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import { isUniversalGroupFilterLike } from 'lib/components/UniversalFilters/utils'
import { Params } from 'scenes/sceneTypes'

import { DateRange, QuickFilterContext } from '~/queries/schema/schema-general'
import { FilterLogicalOperator, PropertyFilterType, UniversalFiltersGroup } from '~/types'

import { updateSearchParams } from '../../utils'
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
            {
                setDateRange: (_, { dateRange }) => dateRange,
            },
        ],
        filterGroup: [
            DEFAULT_FILTER_GROUP as UniversalFiltersGroup,
            {
                setFilterGroup: (_, { filterGroup }) =>
                    filterGroup?.values?.length ? filterGroup : DEFAULT_FILTER_GROUP,
            },
        ],
        filterTestAccounts: [
            DEFAULT_TEST_ACCOUNT as boolean,
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
    listeners(({ actions }) => ({
        setSearchQuery: async ({ searchQuery }) => {
            actions.setTaxonomicSearchQuery(searchQuery)
        },
    })),
])

export interface IssueFilterValues {
    dateRange: DateRange | null
    filterGroup: UniversalFiltersGroup
    filterTestAccounts: boolean
    searchQuery: string
}

export interface IssueFilterActions {
    setDateRange: (dateRange: DateRange) => void
    setSearchQuery: (searchQuery: string) => void
    setFilterGroup: (filterGroup: UniversalFiltersGroup) => void
    setFilterTestAccounts: (filterTestAccounts: boolean) => void
}

export function updateFilterSearchParams(params: Params, values: IssueFilterValues): Params {
    updateSearchParams(params, 'filterTestAccounts', values.filterTestAccounts, DEFAULT_TEST_ACCOUNT)
    updateSearchParams(params, 'searchQuery', values.searchQuery, DEFAULT_SEARCH_QUERY)
    updateSearchParams(params, 'filterGroup', values.filterGroup, DEFAULT_FILTER_GROUP)
    updateSearchParams(params, 'dateRange', values.dateRange, DEFAULT_DATE_RANGE)
    return params
}

export const triggerFilterActions = (params: Params, values: any, actions: IssueFilterActions): void => {
    const dateRange = params.dateRange ?? DEFAULT_DATE_RANGE
    if (!equal(dateRange, values.dateRange)) {
        actions.setDateRange(dateRange)
    }

    const filterGroup = params.filterGroup ?? DEFAULT_FILTER_GROUP
    if (!equal(filterGroup, values.filterGroup)) {
        actions.setFilterGroup(filterGroup)
    }

    const filterTestAccounts = params.filterTestAccounts ?? DEFAULT_TEST_ACCOUNT
    if (!equal(filterTestAccounts, values.filterTestAccounts)) {
        actions.setFilterTestAccounts(filterTestAccounts)
    }

    const newQuery = params.searchQuery ? params.searchQuery.toString() : DEFAULT_SEARCH_QUERY
    if (!equal(newQuery, values.searchQuery)) {
        actions.setSearchQuery(newQuery)
    }
}
