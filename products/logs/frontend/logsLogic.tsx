import { actions, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { DEFAULT_UNIVERSAL_GROUP_FILTER } from 'lib/components/UniversalFilters/universalFiltersLogic'

import { DateRange, LogMessage, LogsQuery } from '~/queries/schema/schema-general'
import { UniversalFiltersGroup } from '~/types'

import type { logsLogicType } from './logsLogicType'

const DEFAULT_DATE_RANGE = { date_from: '-7d', date_to: null }

export const logsLogic = kea<logsLogicType>([
    path(['products', 'logs', 'frontend', 'logsLogic']),

    actions({
        setDateRange: (dateRange: DateRange) => ({ dateRange }),
        setOrderBy: (orderBy: LogsQuery['orderBy']) => ({ orderBy }),
        setSearchTerm: (searchTerm: LogsQuery['searchTerm']) => ({ searchTerm }),
        setResource: (resource: LogsQuery['resource']) => ({ resource }),
        setSeverityLevels: (severityLevels: LogsQuery['severityLevels']) => ({ severityLevels }),
        setWrapBody: (wrapBody: boolean) => ({ wrapBody }),
        setFilterGroup: (filterGroup: UniversalFiltersGroup) => ({ filterGroup }),
    }),

    reducers({
        dateRange: [
            DEFAULT_DATE_RANGE as DateRange,
            {
                setDateRange: (_, { dateRange }) => dateRange,
            },
        ],
        orderBy: [
            'latest' as LogsQuery['orderBy'],
            {
                setOrderBy: (_, { orderBy }) => orderBy,
            },
        ],
        searchTerm: [
            '' as LogsQuery['searchTerm'],
            {
                setSearchTerm: (_, { searchTerm }) => searchTerm,
            },
        ],
        resource: [
            '' as LogsQuery['resource'],
            {
                setResource: (_, { resource }) => resource,
            },
        ],
        severityLevels: [
            [] as LogsQuery['severityLevels'],
            {
                setSeverityLevels: (_, { severityLevels }) => severityLevels,
            },
        ],
        filterGroup: [
            DEFAULT_UNIVERSAL_GROUP_FILTER,
            { persist: false },
            {
                setFilterGroup: (_, { filterGroup }) => filterGroup,
            },
        ],

        wrapBody: [
            true as boolean,
            {
                setWrapBody: (_, { wrapBody }) => wrapBody,
            },
        ],
        hasRunQuery: [
            false as boolean,
            {
                fetchLogsSuccess: () => true,
                fetchLogsFailure: () => true,
            },
        ],
    }),

    loaders(({ values }) => ({
        logs: [
            [] as LogMessage[],
            {
                fetchLogs: async () => {
                    const response = await api.logs.query({
                        query: {
                            limit: 100,
                            offset: values.logs.length,
                            orderBy: values.orderBy,
                            dateRange: values.dateRange,
                            searchTerm: values.searchTerm,
                            resource: values.resource,
                            severityLevels: values.severityLevels,
                        },
                    })
                    return response.results
                },
            },
        ],
    })),

    listeners(({ values, actions }) => {
        const maybeRefreshLogs = (): void => {
            if (values.hasRunQuery) {
                actions.fetchLogs()
            }
        }

        return {
            setDateRange: maybeRefreshLogs,
            setOrderBy: maybeRefreshLogs,
            // TODO: debounce
            // setSearchTerm: maybeRefreshLogs,
            setResource: maybeRefreshLogs,
            setSeverityLevels: maybeRefreshLogs,
            setWrapBody: maybeRefreshLogs,
            setFilterGroup: maybeRefreshLogs,
        }
    }),
])
