import { actions, kea, path, reducers } from 'kea'

import { DateRange } from '~/queries/schema/schema-general'
import { FilterLogicalOperator, UniversalFiltersGroup } from '~/types'

import type { errorFiltersLogicType } from './errorFiltersLogicType'

export const ERROR_TRACKING_DEFAULT_DATE_RANGE = { date_from: '-7d', date_to: null }
export const ERROR_TRACKING_DEFAULT_FILTER_GROUP = {
    type: FilterLogicalOperator.And,
    values: [{ type: FilterLogicalOperator.And, values: [] }],
}
export const ERROR_TRACKING_DEFAULT_TEST_ACCOUNT = false
export const ERROR_TRACKING_DEFAULT_SEARCH_QUERY = ''

export const errorFiltersLogic = kea<errorFiltersLogicType>([
    path(['scenes', 'error-tracking', 'errorFiltersLogic']),

    actions({
        setDateRange: (dateRange: DateRange) => ({ dateRange }),
        setSearchQuery: (searchQuery: string) => ({ searchQuery }),
        setFilterGroup: (filterGroup: UniversalFiltersGroup) => ({ filterGroup }),
        setFilterTestAccounts: (filterTestAccounts: boolean) => ({ filterTestAccounts }),
    }),
    reducers({
        dateRange: [
            ERROR_TRACKING_DEFAULT_DATE_RANGE as DateRange,
            { persist: true },
            {
                setDateRange: (_, { dateRange }) => dateRange,
            },
        ],
        filterGroup: [
            ERROR_TRACKING_DEFAULT_FILTER_GROUP as UniversalFiltersGroup,
            { persist: true },
            {
                setFilterGroup: (_, { filterGroup }) => filterGroup,
            },
        ],
        filterTestAccounts: [
            ERROR_TRACKING_DEFAULT_TEST_ACCOUNT as boolean,
            { persist: true },
            {
                setFilterTestAccounts: (_, { filterTestAccounts }) => filterTestAccounts,
            },
        ],
        searchQuery: [
            ERROR_TRACKING_DEFAULT_SEARCH_QUERY as string,
            {
                setSearchQuery: (_, { searchQuery }) => searchQuery,
            },
        ],
    }),
])
