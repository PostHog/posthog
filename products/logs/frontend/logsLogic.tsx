import { actions, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { DEFAULT_UNIVERSAL_GROUP_FILTER } from 'lib/components/UniversalFilters/universalFiltersLogic'

import { DateRange, LogsQuery } from '~/queries/schema/schema-general'
import { integer } from '~/queries/schema/type-utils'
import { PropertyGroupFilter, UniversalFiltersGroup } from '~/types'

import type { logsLogicType } from './logsLogicType'

const DEFAULT_DATE_RANGE = { date_from: '-1h', date_to: null }

export const logsLogic = kea<logsLogicType>([
    path(['products', 'logs', 'frontend', 'logsLogic']),

    actions({
        runQuery: (debounce?: integer) => ({ debounce }),
        cancelInProgressLogs: (logsAbortController: AbortController | null) => ({ logsAbortController }),
        cancelInProgressSparkline: (sparklineAbortController: AbortController | null) => ({ sparklineAbortController }),
        setLogsAbortController: (logsAbortController: AbortController | null) => ({ logsAbortController }),
        setSparklineAbortController: (sparklineAbortController: AbortController | null) => ({
            sparklineAbortController,
        }),
        setDateRange: (dateRange: DateRange) => ({ dateRange }),
        setOrderBy: (orderBy: LogsQuery['orderBy']) => ({ orderBy }),
        setSearchTerm: (searchTerm: LogsQuery['searchTerm']) => ({ searchTerm }),
        setResource: (resource: LogsQuery['resource']) => ({ resource }),
        setSeverityLevels: (severityLevels: LogsQuery['severityLevels']) => ({ severityLevels }),
        setWrapBody: (wrapBody: boolean) => ({ wrapBody }),
        setFilterGroup: (filterGroup: UniversalFiltersGroup, openFilterOnInsert: boolean = true) => ({
            filterGroup,
            openFilterOnInsert,
        }),
        toggleAttributeBreakdown: (key: string) => ({ key }),
        setExpandedAttributeBreaksdowns: (expandedAttributeBreaksdowns: string[]) => ({ expandedAttributeBreaksdowns }),
    }),

    reducers({
        dateRange: [
            DEFAULT_DATE_RANGE as DateRange,
            {
                setDateRange: (_, { dateRange }) => {
                    return dateRange
                },
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
        logsAbortController: [
            null as AbortController | null,
            {
                setLogsAbortController: (_, { logsAbortController }) => logsAbortController,
            },
        ],
        sparklineAbortController: [
            null as AbortController | null,
            {
                setSparklineAbortController: (_, { sparklineAbortController }) => sparklineAbortController,
            },
        ],
        hasRunQuery: [
            false as boolean,
            {
                fetchLogsSuccess: () => true,
                fetchLogsFailure: () => true,
            },
        ],
        logsLoading: [
            false as boolean,
            {
                fetchLogs: () => true,
                fetchLogsSuccess: () => false,
                fetchLogsFailure: () => true,
            },
        ],
        sparklineLoading: [
            false as boolean,
            {
                fetchSparkline: () => true,
                fetchSparklineSuccess: () => false,
                fetchSparklineFailure: () => true,
            },
        ],
        openFilterOnInsert: [
            false as boolean,
            {
                setFilterGroup: (_, { openFilterOnInsert }) => openFilterOnInsert,
            },
        ],
        expandedAttributeBreaksdowns: [
            [] as string[],
            {
                setExpandedAttributeBreaksdowns: (_, { expandedAttributeBreaksdowns }) => expandedAttributeBreaksdowns,
            },
        ],
    }),

    loaders(({ values, actions }) => ({
        logs: [
            [],
            {
                fetchLogs: async () => {
                    const logsController = new AbortController()
                    const signal = logsController.signal
                    actions.cancelInProgressLogs(logsController)

                    const response = await api.logs.query({
                        query: {
                            limit: 100,
                            offset: values.logs.length,
                            orderBy: values.orderBy,
                            dateRange: values.dateRange,
                            searchTerm: values.searchTerm,
                            resource: values.resource,
                            filterGroup: values.filterGroup as PropertyGroupFilter,
                            severityLevels: values.severityLevels,
                        },
                        signal,
                    })
                    actions.setLogsAbortController(null)
                    return response.results
                },
            },
        ],
        sparkline: [
            [] as any[],
            {
                fetchSparkline: async () => {
                    const sparklineController = new AbortController()
                    const signal = sparklineController.signal
                    actions.cancelInProgressSparkline(sparklineController)

                    const response = await api.logs.sparkline({
                        query: {
                            orderBy: values.orderBy,
                            dateRange: values.dateRange,
                            searchTerm: values.searchTerm,
                            resource: values.resource,
                            filterGroup: values.filterGroup as PropertyGroupFilter,
                            severityLevels: values.severityLevels,
                        },
                        signal,
                    })
                    actions.setSparklineAbortController(null)
                    return response
                },
            },
        ],
    })),

    listeners(({ values, actions }) => {
        const maybeRefreshLogs = (): void => {
            if (values.hasRunQuery) {
                actions.runQuery(300)
            }
        }

        return {
            runQuery: async ({ debounce }, breakpoint) => {
                if (debounce) {
                    await breakpoint(debounce)
                }
                actions.fetchLogs()
                actions.fetchSparkline()
            },
            cancelInProgressLogs: ({ logsAbortController }) => {
                if (values.logsAbortController !== null) {
                    values.logsAbortController.abort('new query started')
                }
                actions.setLogsAbortController(logsAbortController)
            },
            cancelInProgressSparkline: ({ sparklineAbortController }) => {
                if (values.sparklineAbortController !== null) {
                    values.sparklineAbortController.abort('new query started')
                }
                actions.setSparklineAbortController(sparklineAbortController)
            },
            toggleAttributeBreakdown: ({ key }) => {
                const breakdowns = [...values.expandedAttributeBreaksdowns]
                const index = breakdowns.indexOf(key)
                index >= 0 ? breakdowns.splice(index, 1) : breakdowns.push(key)
                actions.setExpandedAttributeBreaksdowns(breakdowns)
            },
            setDateRange: maybeRefreshLogs,
            setOrderBy: maybeRefreshLogs,
            setSearchTerm: maybeRefreshLogs,
            setResource: maybeRefreshLogs,
            setSeverityLevels: maybeRefreshLogs,
            setFilterGroup: maybeRefreshLogs,
        }
    }),
])
