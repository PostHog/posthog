import colors from 'ansi-colors'
import equal from 'fast-deep-equal'
import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { syncSearchParams, updateSearchParams } from '@posthog/products-error-tracking/frontend/utils'

import api from 'lib/api'
import { DEFAULT_UNIVERSAL_GROUP_FILTER } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { dayjs } from 'lib/dayjs'
import { tabAwareActionToUrl } from 'lib/logic/scenes/tabAwareActionToUrl'
import { tabAwareScene } from 'lib/logic/scenes/tabAwareScene'
import { tabAwareUrlToAction } from 'lib/logic/scenes/tabAwareUrlToAction'
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
const DEFAULT_HIGHLIGHTED_LOG_ID = null as string | null
const DEFAULT_ORDER_BY = 'latest' as LogsQuery['orderBy']
const DEFAULT_WRAP_BODY = true
const DEFAULT_PRETTIFY_JSON = true
const DEFAULT_TIMESTAMP_FORMAT = 'absolute' as 'absolute' | 'relative'
const DEFAULT_LOGS_PAGE_SIZE = 100

const parseLogAttributes = (logs: LogMessage[]): void => {
    logs.forEach((row) => {
        Object.keys(row.attributes).forEach((key) => {
            const value = row.attributes[key]
            row.attributes[key] = typeof value === 'string' ? value : JSON.stringify(value)
        })
    })
}

export const logsLogic = kea<logsLogicType>([
    path(['products', 'logs', 'frontend', 'logsLogic']),
    tabAwareScene(),
    tabAwareUrlToAction(({ actions, values }) => {
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
            if (params.highlightedLogId !== undefined && params.highlightedLogId !== values.highlightedLogId) {
                actions.setHighlightedLogId(params.highlightedLogId)
            }
            if (params.orderBy && !equal(params.orderBy, values.orderBy)) {
                actions.setOrderBy(params.orderBy)
            }
            if (params.wrapBody !== undefined && params.wrapBody !== values.wrapBody) {
                actions.setWrapBody(params.wrapBody)
            }
            if (params.prettifyJson !== undefined && params.prettifyJson !== values.prettifyJson) {
                actions.setPrettifyJson(params.prettifyJson)
            }
            if (params.timestampFormat && params.timestampFormat !== values.timestampFormat) {
                actions.setTimestampFormat(params.timestampFormat)
            }
        }
        return {
            '*': urlToAction,
        }
    }),

    tabAwareActionToUrl(({ actions, values }) => {
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
                updateSearchParams(params, 'highlightedLogId', values.highlightedLogId, DEFAULT_HIGHLIGHTED_LOG_ID)
                updateSearchParams(params, 'orderBy', values.orderBy, DEFAULT_ORDER_BY)
                actions.runQuery()
                return params
            })
        }

        const updateHighlightURL = (): [
            string,
            Params,
            Record<string, any>,
            {
                replace: boolean
            },
        ] => {
            return syncSearchParams(router, (params: Params) => {
                updateSearchParams(params, 'highlightedLogId', values.highlightedLogId, DEFAULT_HIGHLIGHTED_LOG_ID)
                return params
            })
        }

        const updateUrlWithDisplayPreferences = (): [
            string,
            Params,
            Record<string, any>,
            {
                replace: boolean
            },
        ] => {
            return syncSearchParams(router, (params: Params) => {
                updateSearchParams(params, 'wrapBody', values.wrapBody, DEFAULT_WRAP_BODY)
                updateSearchParams(params, 'prettifyJson', values.prettifyJson, DEFAULT_PRETTIFY_JSON)
                updateSearchParams(params, 'timestampFormat', values.timestampFormat, DEFAULT_TIMESTAMP_FORMAT)
                return params
            })
        }

        return {
            setDateRange: () => buildURL(),
            setFilterGroup: () => buildURL(),
            setSearchTerm: () => buildURL(),
            setSeverityLevels: () => buildURL(),
            setServiceNames: () => buildURL(),
            setHighlightedLogId: () => updateHighlightURL(),
            setOrderBy: () => buildURL(),
            setWrapBody: () => updateUrlWithDisplayPreferences(),
            setPrettifyJson: () => updateUrlWithDisplayPreferences(),
            setTimestampFormat: () => updateUrlWithDisplayPreferences(),
        }
    }),

    actions({
        runQuery: (debounce?: integer) => ({ debounce }),
        loadMoreLogs: true,
        clearLogs: true,
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
        setHighlightedLogId: (highlightedLogId: string | null) => ({ highlightedLogId }),
        setHasMoreLogsToLoad: (hasMoreLogsToLoad: boolean) => ({ hasMoreLogsToLoad }),
    }),

    reducers({
        dateRange: [
            DEFAULT_DATE_RANGE as DateRange,
            {
                setDateRange: (_, { dateRange }) => dateRange,
            },
        ],
        orderBy: [
            DEFAULT_ORDER_BY,
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
        severityLevels: [
            DEFAULT_SEVERITY_LEVELS,
            {
                setSeverityLevels: (_, { severityLevels }) => severityLevels,
            },
        ],
        serviceNames: [
            DEFAULT_SERVICE_NAMES,
            {
                setServiceNames: (_, { serviceNames }) => serviceNames,
            },
        ],
        filterGroup: [
            DEFAULT_UNIVERSAL_GROUP_FILTER,
            {
                setFilterGroup: (_, { filterGroup }) => filterGroup,
            },
        ],
        wrapBody: [
            DEFAULT_WRAP_BODY as boolean,
            {
                setWrapBody: (_, { wrapBody }) => wrapBody,
            },
        ],
        prettifyJson: [
            DEFAULT_PRETTIFY_JSON as boolean,
            {
                setPrettifyJson: (_, { prettifyJson }) => prettifyJson,
            },
        ],
        timestampFormat: [
            DEFAULT_TIMESTAMP_FORMAT as 'absolute' | 'relative',
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
                fetchLogsFailure: () => false,
            },
        ],
        sparklineLoading: [
            false as boolean,
            {
                fetchSparkline: () => true,
                fetchSparklineSuccess: () => false,
                fetchSparklineFailure: () => false,
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
        highlightedLogId: [
            DEFAULT_HIGHLIGHTED_LOG_ID,
            {
                setHighlightedLogId: (_, { highlightedLogId }) => highlightedLogId,
            },
        ],
        hasMoreLogsToLoad: [
            true as boolean,
            {
                setHasMoreLogsToLoad: (_, { hasMoreLogsToLoad }) => hasMoreLogsToLoad,
                clearLogs: () => true,
            },
        ],
    }),

    loaders(({ values, actions }) => ({
        logs: [
            [] as LogMessage[],
            {
                clearLogs: () => [],
                fetchLogs: async () => {
                    const logsController = new AbortController()
                    const signal = logsController.signal
                    actions.cancelInProgressLogs(logsController)

                    const response = await api.logs.query({
                        query: {
                            limit: DEFAULT_LOGS_PAGE_SIZE,
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
                    actions.setHasMoreLogsToLoad(!!response.hasMore)
                    parseLogAttributes(response.results)
                    return response.results
                },
                loadMoreLogs: async (_, breakpoint) => {
                    const logsController = new AbortController()
                    const signal = logsController.signal
                    actions.cancelInProgressLogs(logsController)

                    let dateRange: DateRange

                    if (values.orderBy === 'earliest') {
                        if (!values.newestLogTimestamp) {
                            return values.logs
                        }
                        dateRange = {
                            date_from: values.newestLogTimestamp,
                            date_to: values.utcDateRange.date_to,
                        }
                    } else {
                        if (!values.oldestLogTimestamp) {
                            return values.logs
                        }
                        dateRange = {
                            date_from: values.utcDateRange.date_from,
                            date_to: values.oldestLogTimestamp,
                        }
                    }
                    await breakpoint(300)
                    const response = await api.logs.query({
                        query: {
                            limit: DEFAULT_LOGS_PAGE_SIZE,
                            orderBy: values.orderBy,
                            dateRange,
                            searchTerm: values.searchTerm,
                            filterGroup: values.filterGroup as PropertyGroupFilter,
                            severityLevels: values.severityLevels,
                            serviceNames: values.serviceNames,
                        },
                        signal,
                    })
                    actions.setLogsAbortController(null)
                    actions.setHasMoreLogsToLoad(!!response.hasMore)
                    parseLogAttributes(response.results)
                    return [...values.logs, ...response.results]
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
        visibleLogsTimeRange: [
            (s) => [s.parsedLogs, s.orderBy],
            (
                parsedLogs: ParsedLogMessage[],
                orderBy: LogsQuery['orderBy']
            ): { date_from: string; date_to: string } | null => {
                if (parsedLogs.length === 0) {
                    return null
                }
                const firstTimestamp = parsedLogs[0].timestamp
                const lastTimestamp = parsedLogs[parsedLogs.length - 1].timestamp

                // When orderBy is 'latest', first log is newest, last log is oldest
                // When orderBy is 'earliest', first log is oldest, last log is newest
                if (orderBy === 'latest') {
                    return {
                        date_from: dayjs(lastTimestamp).toISOString(),
                        date_to: dayjs(firstTimestamp).toISOString(),
                    }
                }
                return {
                    date_from: dayjs(firstTimestamp).toISOString(),
                    date_to: dayjs(lastTimestamp).toISOString(),
                }
            },
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
        oldestLogTimestamp: [
            (s) => [s.logs],
            (logs): string | null => {
                if (!logs.length) {
                    return null
                }
                const oldest = logs.reduce((min, log) => {
                    const logTime = dayjs(log.timestamp)
                    return !min || logTime.isBefore(dayjs(min)) ? log.timestamp : min
                }, logs[0].timestamp)
                return oldest
            },
        ],
        newestLogTimestamp: [
            (s) => [s.logs],
            (logs): string | null => {
                if (!logs.length) {
                    return null
                }
                const newest = logs.reduce((max, log) => {
                    const logTime = dayjs(log.timestamp)
                    return !max || logTime.isAfter(dayjs(max)) ? log.timestamp : max
                }, logs[0].timestamp)
                return newest
            },
        ],
    })),

    listeners(({ values, actions }) => ({
        runQuery: async ({ debounce }, breakpoint) => {
            if (debounce) {
                await breakpoint(debounce)
            }
            actions.clearLogs()
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
