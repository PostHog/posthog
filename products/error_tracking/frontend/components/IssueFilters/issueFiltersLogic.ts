import equal from 'fast-deep-equal'
import { actions, kea, key, listeners, path, props, reducers } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'
import posthog from 'posthog-js'

import { Params } from 'scenes/sceneTypes'

import { DateRange } from '~/queries/schema/schema-general'
import { FilterLogicalOperator, PropertyFilterType, PropertyGroupFilter, UniversalFiltersGroup } from '~/types'

import { syncSearchParams, updateSearchParams } from '../../utils'
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

    listeners(({ values }) => ({
        setFilterGroup: ({ filterGroup }) => {
            // Analyze filter categories used
            const filterCategories: string[] = []
            let filterCount = 0

            filterGroup.values.forEach((group) => {
                if (group.values) {
                    group.values.forEach((filter: PropertyGroupFilter) => {
                        filterCount++
                        const type = filter.type
                        if (type === PropertyFilterType.Person && !filterCategories.includes('person_properties')) {
                            filterCategories.push('person_properties')
                        } else if (
                            type === PropertyFilterType.Event &&
                            !filterCategories.includes('event_properties')
                        ) {
                            filterCategories.push('event_properties')
                        } else if (type === PropertyFilterType.Cohort && !filterCategories.includes('cohorts')) {
                            filterCategories.push('cohorts')
                        } else if (type === PropertyFilterType.HogQL && !filterCategories.includes('sql_expression')) {
                            filterCategories.push('sql_expression')
                        }
                    })
                }
            })

            posthog.capture('error_tracking_filter_applied', {
                filter_categories_used: filterCategories,
                filter_count: filterCount,
                has_search_query: !!values.searchQuery,
                filter_test_accounts: values.filterTestAccounts,
            })
        },
        setSearchQuery: ({ searchQuery }) => {
            const filterGroup = values.filterGroup

            const filterCount = filterGroup.values.reduce((count, group) => count + (group.values?.length || 0), 0)

            posthog.capture('error_tracking_filter_applied', {
                filter_categories_used: [], // Search doesn't use categories
                filter_count: filterCount,
                has_search_query: !!searchQuery,
                filter_test_accounts: values.filterTestAccounts,
            })
        },
        setFilterTestAccounts: ({ filterTestAccounts }) => {
            const filterGroup = values.filterGroup

            const filterCount = filterGroup.values.reduce((count, group) => count + (group.values?.length || 0), 0)

            posthog.capture('error_tracking_filter_applied', {
                filter_categories_used: [],
                filter_count: filterCount,
                has_search_query: !!values.searchQuery,
                filter_test_accounts: filterTestAccounts,
            })
        },
    })),

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
            if (params.searchQuery && !equal(params.searchQuery, values.searchQuery)) {
                actions.setSearchQuery(params.searchQuery)
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
