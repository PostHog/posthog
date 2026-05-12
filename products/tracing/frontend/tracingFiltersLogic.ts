import { actions, kea, path, reducers, selectors } from 'kea'

import { DEFAULT_UNIVERSAL_GROUP_FILTER } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { dayjs } from 'lib/dayjs'

import { DateRange } from '~/queries/schema/schema-general'
import { UniversalFiltersGroup } from '~/types'

import type { tracingFiltersLogicType } from './tracingFiltersLogicType'

export const DEFAULT_DATE_RANGE: DateRange = { date_from: '-1h', date_to: null }
export const DEFAULT_SERVICE_NAMES: string[] = []
export const DEFAULT_ORDER_BY = 'latest' as const

export type TracingOrderBy = 'latest' | 'earliest'

export interface TracingFilters {
    dateRange: DateRange
    serviceNames: string[]
    filterGroup: UniversalFiltersGroup
    orderBy: TracingOrderBy
    compareMode: boolean
    /** Relative offset such as `-1h`, `-1d`. When null, the comparison window is the immediately previous period of equal length. */
    compareTo: string | null
}

export const tracingFiltersLogic = kea<tracingFiltersLogicType>([
    path(['products', 'tracing', 'frontend', 'tracingFiltersLogic']),

    actions({
        setDateRange: (dateRange: DateRange) => ({ dateRange }),
        setServiceNames: (serviceNames: string[]) => ({ serviceNames }),
        setFilterGroup: (filterGroup: UniversalFiltersGroup) => ({ filterGroup }),
        setOrderBy: (orderBy: TracingOrderBy) => ({ orderBy }),
        setCompareMode: (compareMode: boolean) => ({ compareMode }),
        setCompareTo: (compareTo: string | null) => ({ compareTo }),
        setFilters: (filters: Partial<TracingFilters>) => ({ filters }),
    }),

    reducers({
        dateRange: [
            DEFAULT_DATE_RANGE as DateRange,
            {
                setDateRange: (_, { dateRange }) => dateRange,
                setFilters: (state, { filters }) => filters.dateRange ?? state,
            },
        ],
        serviceNames: [
            DEFAULT_SERVICE_NAMES as string[],
            {
                setServiceNames: (_, { serviceNames }) => serviceNames,
                setFilters: (state, { filters }) => filters.serviceNames ?? state,
            },
        ],
        filterGroup: [
            DEFAULT_UNIVERSAL_GROUP_FILTER as UniversalFiltersGroup,
            {
                setFilterGroup: (_, { filterGroup }) =>
                    filterGroup && filterGroup.values ? filterGroup : DEFAULT_UNIVERSAL_GROUP_FILTER,
                setFilters: (state, { filters }) =>
                    filters.filterGroup && filters.filterGroup.values ? filters.filterGroup : state,
            },
        ],
        orderBy: [
            DEFAULT_ORDER_BY as TracingOrderBy,
            {
                setOrderBy: (_, { orderBy }) => orderBy,
                setFilters: (state, { filters }) => (filters.orderBy as TracingOrderBy) ?? state,
            },
        ],
        compareMode: [
            false as boolean,
            {
                setCompareMode: (_, { compareMode }) => compareMode,
                setFilters: (state, { filters }) => filters.compareMode ?? state,
            },
        ],
        compareTo: [
            null as string | null,
            {
                setCompareTo: (_, { compareTo }) => compareTo,
                setFilters: (state, { filters }) => filters.compareTo ?? state,
            },
        ],
    }),

    selectors({
        filters: [
            (s) => [s.dateRange, s.serviceNames, s.filterGroup, s.orderBy, s.compareMode, s.compareTo],
            (dateRange, serviceNames, filterGroup, orderBy, compareMode, compareTo): TracingFilters => ({
                dateRange,
                serviceNames,
                filterGroup,
                orderBy,
                compareMode,
                compareTo,
            }),
        ],
        utcDateRange: [
            (s) => [s.dateRange],
            (dateRange: DateRange) => ({
                date_from: dayjs(dateRange.date_from).isValid()
                    ? dayjs(dateRange.date_from).toISOString()
                    : dateRange.date_from,
                date_to: dayjs(dateRange.date_to).isValid()
                    ? dayjs(dateRange.date_to).toISOString()
                    : dateRange.date_to,
            }),
        ],
    }),
])
