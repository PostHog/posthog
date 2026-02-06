import { actions, kea, key, path, props, reducers, selectors } from 'kea'

import { DEFAULT_UNIVERSAL_GROUP_FILTER } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { dayjs } from 'lib/dayjs'

import { DateRange, LogSeverityLevel, LogsQuery } from '~/queries/schema/schema-general'
import { UniversalFiltersGroup } from '~/types'

import { LogsViewerFilters } from 'products/logs/frontend/components/LogsViewer/config/types'

import type { logsViewerFiltersLogicType } from './logsViewerFiltersLogicType'

export const DEFAULT_DATE_RANGE = { date_from: '-1h', date_to: null }
const VALID_SEVERITY_LEVELS: readonly LogSeverityLevel[] = ['trace', 'debug', 'info', 'warn', 'error', 'fatal']
export const DEFAULT_SEVERITY_LEVELS = [] as LogsQuery['severityLevels']

export const isValidSeverityLevel = (level: string): level is LogSeverityLevel =>
    VALID_SEVERITY_LEVELS.includes(level as LogSeverityLevel)

export const DEFAULT_SERVICE_NAMES = [] as LogsQuery['serviceNames']

export interface LogsViewerFiltersLogicProps {
    id: string
}

export const logsViewerFiltersLogic = kea<logsViewerFiltersLogicType>([
    path(['products', 'logs', 'frontend', 'components', 'LogsViewer', 'Filters', 'logsViewerFiltersLogic']),
    props({ id: 'default' } as LogsViewerFiltersLogicProps),
    key((props) => props.id),

    actions({
        // setting individual filters
        setDateRange: (dateRange: DateRange) => ({ dateRange }),
        setSearchTerm: (searchTerm: LogsQuery['searchTerm']) => ({ searchTerm }),
        setSeverityLevels: (severityLevels: LogsQuery['severityLevels']) => ({ severityLevels }),
        setServiceNames: (serviceNames: LogsQuery['serviceNames']) => ({ serviceNames }),
        setFilterGroup: (filterGroup: UniversalFiltersGroup, openFilterOnInsert: boolean = true) => ({
            filterGroup,
            openFilterOnInsert,
        }),

        // setting all filters at once
        setFilters: (filters: Partial<LogsViewerFilters>, pushToHistory: boolean = true) => ({
            filters,
            pushToHistory,
        }),
    }),

    reducers({
        dateRange: [
            DEFAULT_DATE_RANGE as DateRange,
            {
                setDateRange: (_, { dateRange }) => dateRange,
                setFilters: (state, { filters }) => filters.dateRange ?? state,
            },
        ],
        searchTerm: [
            '' as LogsQuery['searchTerm'],
            {
                setSearchTerm: (_, { searchTerm }) => searchTerm,
                setFilters: (state, { filters }) => filters.searchTerm ?? state,
            },
        ],
        severityLevels: [
            DEFAULT_SEVERITY_LEVELS as LogsQuery['severityLevels'],
            {
                setSeverityLevels: (_, { severityLevels }) => severityLevels,
                setFilters: (state, { filters }) => filters.severityLevels ?? state,
            },
        ],
        serviceNames: [
            DEFAULT_SERVICE_NAMES as LogsQuery['serviceNames'],
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
        openFilterOnInsert: [
            false as boolean,
            {
                setFilterGroup: (_, { openFilterOnInsert }) => openFilterOnInsert,
            },
        ],
    }),

    selectors({
        tabId: [(_, p) => [p.id], (id: string) => id],
        filters: [
            (s) => [s.dateRange, s.searchTerm, s.severityLevels, s.serviceNames, s.filterGroup],
            (
                dateRange: DateRange,
                searchTerm: LogsQuery['searchTerm'],
                severityLevels: LogsQuery['severityLevels'],
                serviceNames: LogsQuery['serviceNames'],
                filterGroup: UniversalFiltersGroup
            ): LogsViewerFilters => ({ dateRange, searchTerm, severityLevels, serviceNames, filterGroup }),
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
                explicitDate: dateRange.explicitDate,
            }),
        ],
    }),
])
