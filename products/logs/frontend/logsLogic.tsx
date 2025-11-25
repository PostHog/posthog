import colors from 'ansi-colors'
import equal from 'fast-deep-equal'
import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { syncSearchParams, updateSearchParams } from '@posthog/products-error-tracking/frontend/utils'

import api from 'lib/api'
import { DEFAULT_UNIVERSAL_GROUP_FILTER } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { dayjs } from 'lib/dayjs'
import { humanFriendlyDetailedTime } from 'lib/utils'
import { Params } from 'scenes/sceneTypes'

import { DateRange, LogMessage, LogsQuery } from '~/queries/schema/schema-general'
import { integer } from '~/queries/schema/type-utils'
import { JsonType, PropertyFilterType, PropertyGroupFilter, PropertyOperator, UniversalFiltersGroup } from '~/types'

import { zoomDateRange } from './filters/zoom-utils'
import type { logsLogicType } from './logsLogicType'
import { ParsedLogMessage } from './types'

const DEFAULT_DATE_RANGE = { date_from: '-1h', date_to: null }
const DEFAULT_SEVERITY_LEVELS = [] as LogsQuery['severityLevels']
const DEFAULT_SERVICE_NAMES = [] as LogsQuery['serviceNames']
const DEFAULT_ORDER_BY = 'latest' as LogsQuery['orderBy']

export const logsLogic = kea<logsLogicType>([
    path(['products', 'logs', 'frontend', 'logsLogic']),

    urlToAction(({ actions, values }) => {
        const urlToAction = (_: any, params: Params): void => {
            if (params.dateRange && !equal(params.dateRange, values.dateRange)) {
                actions.setDateRange(params.dateRange)
            }
            if (params.filterGroup && !equal(params.filterGroup, values.filterGroup)) {
                actions.setFilterGroup(params.filterGroup, false)
            }
            if (params.searchTerm && !equal(params.searchTerm, values.searchTerm)) {
                actions.setSearchTerm(params.searchTerm)
            }
            if (params.severityLevels && !equal(params.severityLevels, values.severityLevels)) {
                actions.setSeverityLevels(params.severityLevels)
            }
            if (params.serviceNames && !equal(params.serviceNames, values.serviceNames)) {
                actions.setServiceNames(params.serviceNames)
            }
            if (params.orderBy && !equal(params.orderBy, values.orderBy)) {
                actions.setOrderBy(params.orderBy)
            }
        }
        return {
            '*': urlToAction,
        }
    }),

    actionToUrl(({ actions, values }) => {
        const buildURL = (): [
            string,
            Params,
            Record<string, any>,
            {
                replace: boolean
            },
        ] => {
            return syncSearchParams(router, (params: Params) => {
                updateSearchParams(params, 'searchTerm', values.searchTerm, '')
                updateSearchParams(params, 'filterGroup', values.filterGroup, DEFAULT_UNIVERSAL_GROUP_FILTER)
                updateSearchParams(params, 'dateRange', values.dateRange, DEFAULT_DATE_RANGE)
                updateSearchParams(params, 'severityLevels', values.severityLevels, DEFAULT_SEVERITY_LEVELS)
                updateSearchParams(params, 'serviceNames', values.serviceNames, DEFAULT_SERVICE_NAMES)
                updateSearchParams(params, 'orderBy', values.orderBy, DEFAULT_ORDER_BY)
                actions.runQuery()
                return params
            })
        }

        return {
            setDateRange: () => buildURL(),
            setFilterGroup: () => buildURL(),
            setSearchTerm: () => buildURL(),
            setSeverityLevels: () => buildURL(),
            setServiceNames: () => buildURL(),
            setOrderBy: () => buildURL(),
        }
    }),

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
        setSeverityLevels: (severityLevels: LogsQuery['severityLevels']) => ({ severityLevels }),
        setServiceNames: (serviceNames: LogsQuery['serviceNames']) => ({ serviceNames }),
        setWrapBody: (wrapBody: boolean) => ({ wrapBody }),
        setPrettifyJson: (prettifyJson: boolean) => ({ prettifyJson }),
        setFilterGroup: (filterGroup: UniversalFiltersGroup, openFilterOnInsert: boolean = true) => ({
            filterGroup,
            openFilterOnInsert,
        }),
        toggleAttributeBreakdown: (key: string) => ({ key }),
        setExpandedAttributeBreaksdowns: (expandedAttributeBreaksdowns: string[]) => ({ expandedAttributeBreaksdowns }),
        zoomDateRange: (multiplier: number) => ({ multiplier }),
        setDateRangeFromSparkline: (startIndex: number, endIndex: number) => ({ startIndex, endIndex }),
        setTimestampFormat: (timestampFormat: 'absolute' | 'relative') => ({ timestampFormat }),
        addFilter: (key: string, value: string, operator: PropertyOperator = PropertyOperator.Exact) => ({
            key,
            value,
            operator,
        }),
        togglePinLog: (logId: string) => ({ logId }),
        pinLog: (log: LogMessage) => ({ log }),
        unpinLog: (logId: string) => ({ logId }),
    }),

    reducers({
        dateRange: [
            DEFAULT_DATE_RANGE as DateRange,
            { persist: true },
            {
                setDateRange: (_, { dateRange }) => dateRange,
            },
        ],
        orderBy: [
            DEFAULT_ORDER_BY,
            { persist: true },
            {
                setOrderBy: (_, { orderBy }) => orderBy,
            },
        ],
        searchTerm: [
            '' as LogsQuery['searchTerm'],
            { persist: true },
            {
                setSearchTerm: (_, { searchTerm }) => searchTerm,
            },
        ],
        severityLevels: [
            DEFAULT_SEVERITY_LEVELS,
            { persist: true },
            {
                setSeverityLevels: (_, { severityLevels }) => severityLevels,
            },
        ],
        serviceNames: [
            DEFAULT_SERVICE_NAMES,
            { persist: true },
            {
                setServiceNames: (_, { serviceNames }) => serviceNames,
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
        prettifyJson: [
            true as boolean,
            { persist: true },
            {
                setPrettifyJson: (_, { prettifyJson }) => prettifyJson,
            },
        ],
        timestampFormat: [
            'absolute' as 'absolute' | 'relative',
            { persist: true },
            {
                setTimestampFormat: (_, { timestampFormat }) => timestampFormat,
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
        pinnedLogs: [
            [] as LogMessage[],
            { persist: true },
            {
                pinLog: (state, { log }) => [...state, log],
                unpinLog: (state, { logId }) => state.filter((log) => log.uuid !== logId),
            },
        ],
    }),

    loaders(({ values, actions }) => ({
        logs: [
            [] as LogMessage[],
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
                            dateRange: values.utcDateRange,
                            searchTerm: values.searchTerm,
                            filterGroup: values.filterGroup as PropertyGroupFilter,
                            severityLevels: values.severityLevels,
                            serviceNames: values.serviceNames,
                        },
                        signal,
                    })
                    actions.setLogsAbortController(null)
                    response.results.forEach((row) => {
                        Object.keys(row.attributes).forEach((key) => {
                            const value = row.attributes[key]
                            row.attributes[key] = typeof value === 'string' ? value : JSON.stringify(value)
                        })
                    })
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
                            dateRange: values.utcDateRange,
                            searchTerm: values.searchTerm,
                            filterGroup: values.filterGroup as PropertyGroupFilter,
                            severityLevels: values.severityLevels,
                            serviceNames: values.serviceNames,
                        },
                        signal,
                    })
                    actions.setSparklineAbortController(null)
                    return response
                },
            },
        ],
    })),

    selectors(() => ({
        utcDateRange: [
            (s) => [s.dateRange],
            (dateRange) => ({
                date_from: dayjs(dateRange.date_from).isValid()
                    ? dayjs(dateRange.date_from).toISOString()
                    : dateRange.date_from,
                date_to: dayjs(dateRange.date_to).isValid()
                    ? dayjs(dateRange.date_to).toISOString()
                    : dateRange.date_to,
                explicitDate: dateRange.explicitDate,
            }),
        ],
        parsedLogs: [
            (s) => [s.logs],
            (logs: LogMessage[]): ParsedLogMessage[] => {
                return logs.map((log: LogMessage) => {
                    const cleanBody = colors.unstyle(log.body)
                    let parsedBody: JsonType | null = null
                    try {
                        parsedBody = JSON.parse(cleanBody)
                    } catch {
                        // Not JSON, that's fine
                    }
                    return { ...log, cleanBody, parsedBody }
                })
            },
        ],
        pinnedParsedLogs: [
            (s) => [s.pinnedLogs],
            (pinnedLogs: LogMessage[]): ParsedLogMessage[] => {
                return pinnedLogs.map((log: LogMessage) => {
                    const cleanBody = colors.unstyle(log.body)
                    let parsedBody: JsonType | null = null
                    try {
                        parsedBody = JSON.parse(cleanBody)
                    } catch {
                        // Not JSON, that's fine
                    }
                    return { ...log, cleanBody, parsedBody }
                })
            },
        ],
        isPinned: [
            (s) => [s.pinnedLogs],
            (pinnedLogs: LogMessage[]) => (logId: string) => pinnedLogs.some((log) => log.uuid === logId),
        ],
        sparklineData: [
            (s) => [s.sparkline],
            (sparkline) => {
                let lastTime = ''
                let i = -1
                const labels: string[] = []
                const dates: string[] = []
                const data = Object.entries(
                    sparkline.reduce((accumulator, currentItem) => {
                        if (currentItem.time !== lastTime) {
                            labels.push(humanFriendlyDetailedTime(currentItem.time))
                            dates.push(currentItem.time)
                            lastTime = currentItem.time
                            i++
                        }
                        const key = currentItem.level
                        if (!accumulator[key]) {
                            accumulator[key] = Array(sparkline.length)
                        }
                        accumulator[key][i] = currentItem.count
                        return accumulator
                    }, {})
                )
                    .map(([level, data]) => ({
                        name: level,
                        values: data as number[],
                        color: {
                            fatal: 'danger-dark',
                            error: 'danger',
                            warn: 'warning',
                            info: 'brand-blue',
                            debug: 'muted',
                            trace: 'muted-alt',
                        }[level],
                    }))
                    .filter((series) => series.values.reduce((a, b) => a + b) > 0)

                return { data, labels, dates }
            },
        ],
    })),

    listeners(({ values, actions }) => ({
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
        zoomDateRange: ({ multiplier }) => {
            const newDateRange = zoomDateRange(values.dateRange, multiplier)
            actions.setDateRange(newDateRange)
        },
        setDateRangeFromSparkline: ({ startIndex, endIndex }) => {
            const dates = values.sparklineData.dates
            const dateFrom = dates[startIndex]
            const dateTo = dates[endIndex + 1]

            if (!dateFrom) {
                return
            }

            // NOTE: I don't know how accurate this really is but its a good starting point
            const newDateRange = {
                date_from: dateFrom,
                date_to: dateTo,
            }
            actions.setDateRange(newDateRange)
        },
        addFilter: ({ key, value, operator }) => {
            const currentGroup = values.filterGroup.values[0] as UniversalFiltersGroup

            const newGroup: UniversalFiltersGroup = {
                ...currentGroup,
                values: [
                    ...currentGroup.values,
                    {
                        key,
                        value: [value],
                        operator,
                        type: PropertyFilterType.Log,
                    },
                ],
            }

            actions.setFilterGroup({ ...values.filterGroup, values: [newGroup] }, false)
        },
        togglePinLog: ({ logId }) => {
            const isPinned = values.pinnedLogs.some((log) => log.uuid === logId)
            if (isPinned) {
                actions.unpinLog(logId)
            } else {
                const logToPin = values.logs.find((log) => log.uuid === logId)
                if (logToPin) {
                    actions.pinLog(logToPin)
                }
            }
        },
    })),
])
