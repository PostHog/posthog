import colors from 'ansi-colors'
import equal from 'fast-deep-equal'
import { actions, afterMount, events, kea, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'
import { syncSearchParams, updateSearchParams } from '@posthog/products-error-tracking/frontend/utils'

import api from 'lib/api'
import { DEFAULT_UNIVERSAL_GROUP_FILTER } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { dayjs } from 'lib/dayjs'
import { tabAwareActionToUrl } from 'lib/logic/scenes/tabAwareActionToUrl'
import { tabAwareScene } from 'lib/logic/scenes/tabAwareScene'
import { tabAwareUrlToAction } from 'lib/logic/scenes/tabAwareUrlToAction'
import { humanFriendlyDetailedTime } from 'lib/utils'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { Params } from 'scenes/sceneTypes'

import { DateRange, LogMessage, LogsQuery } from '~/queries/schema/schema-general'
import { integer } from '~/queries/schema/type-utils'
import {
    JsonType,
    PropertyFilterType,
    PropertyGroupFilter,
    PropertyOperator,
    UniversalFiltersGroup,
    UniversalFiltersGroupValue,
} from '~/types'

import { zoomDateRange } from './filters/zoom-utils'
import type { logsLogicType } from './logsLogicType'
import { LogsOrderBy, ParsedLogMessage } from './types'

const DEFAULT_DATE_RANGE = { date_from: '-1h', date_to: null }
const DEFAULT_SEVERITY_LEVELS = [] as LogsQuery['severityLevels']
const DEFAULT_SERVICE_NAMES = [] as LogsQuery['serviceNames']
const DEFAULT_HIGHLIGHTED_LOG_ID = null as string | null
const DEFAULT_ORDER_BY = 'latest' as LogsQuery['orderBy']
const DEFAULT_LOGS_PAGE_SIZE: number = 250
const DEFAULT_INITIAL_LOGS_LIMIT = null as number | null
const NEW_QUERY_STARTED_ERROR_MESSAGE = 'new query started' as const
const DEFAULT_LIVE_TAIL_POLL_INTERVAL_MS = 1000
const DEFAULT_LIVE_TAIL_POLL_INTERVAL_MAX_MS = 5000

const parseLogAttributes = (logs: LogMessage[]): void => {
    logs.forEach((row) => {
        Object.keys(row.attributes).forEach((key) => {
            const value = row.attributes[key]
            row.attributes[key] = typeof value === 'string' ? value : JSON.stringify(value)
        })
    })
}

export interface LogsLogicProps {
    tabId: string
}

export const logsLogic = kea<logsLogicType>([
    props({} as LogsLogicProps),
    path(['products', 'logs', 'frontend', 'logsLogic']),
    tabAwareScene(),
    tabAwareUrlToAction(({ actions, values }) => {
        const urlToAction = (_: any, params: Params): void => {
            if (params.dateRange) {
                try {
                    const dateRange =
                        typeof params.dateRange === 'string' ? JSON.parse(params.dateRange) : params.dateRange
                    if (!equal(dateRange, values.dateRange)) {
                        actions.setDateRange(dateRange)
                    }
                } catch {
                    // Ignore malformed dateRange JSON in URL
                }
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
            if (+params.logsPageSize && +params.logsPageSize !== values.logsPageSize) {
                actions.setLogsPageSize(+params.logsPageSize)
            }
            if (params.initialLogsLimit != null && +params.initialLogsLimit !== values.initialLogsLimit) {
                actions.setInitialLogsLimit(+params.initialLogsLimit)
            }
        }
        return {
            '*': urlToAction,
        }
    }),

    tabAwareActionToUrl(({ actions, values }) => {
        const buildUrlAndRunQuery = (): [
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
                updateSearchParams(params, 'logsPageSize', values.logsPageSize, DEFAULT_LOGS_PAGE_SIZE)
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

        const updateUrlWithPageSize = (): [
            string,
            Params,
            Record<string, any>,
            {
                replace: boolean
            },
        ] => {
            return syncSearchParams(router, (params: Params) => {
                updateSearchParams(params, 'logsPageSize', values.logsPageSize, DEFAULT_LOGS_PAGE_SIZE)
                actions.applyLogsPageSize(values.logsPageSize)
                return params
            })
        }

        const clearInitialLogsLimit = (): [
            string,
            Params,
            Record<string, any>,
            {
                replace: boolean
            },
        ] => {
            return syncSearchParams(router, (params: Params) => {
                updateSearchParams(params, 'initialLogsLimit', null, DEFAULT_INITIAL_LOGS_LIMIT)
                return params
            })
        }

        return {
            fetchLogsSuccess: () => clearInitialLogsLimit(),
            setDateRange: () => buildUrlAndRunQuery(),
            setFilterGroup: () => buildUrlAndRunQuery(),
            setSearchTerm: () => buildUrlAndRunQuery(),
            setSeverityLevels: () => buildUrlAndRunQuery(),
            setServiceNames: () => buildUrlAndRunQuery(),
            setOrderBy: () => buildUrlAndRunQuery(),
            setLogsPageSize: () => updateUrlWithPageSize(),
            setHighlightedLogId: () => updateHighlightURL(),
        }
    }),

    actions({
        runQuery: (debounce?: integer) => ({ debounce }),
        fetchNextLogsPage: (limit?: number) => ({ limit }),
        truncateLogs: (limit: number) => ({ limit }),
        applyLogsPageSize: (logsPageSize: number) => ({ logsPageSize }),
        clearLogs: true,
        cancelInProgressLogs: (logsAbortController: AbortController | null) => ({ logsAbortController }),
        cancelInProgressSparkline: (sparklineAbortController: AbortController | null) => ({ sparklineAbortController }),
        cancelInProgressLiveTail: (liveTailAbortController: AbortController | null) => ({ liveTailAbortController }),
        setLogsAbortController: (logsAbortController: AbortController | null) => ({ logsAbortController }),
        setSparklineAbortController: (sparklineAbortController: AbortController | null) => ({
            sparklineAbortController,
        }),
        setLiveTailAbortController: (liveTailAbortController: AbortController | null) => ({
            liveTailAbortController,
        }),
        setDateRange: (dateRange: DateRange) => ({ dateRange }),
        setOrderBy: (orderBy: LogsOrderBy) => ({ orderBy }),
        setSearchTerm: (searchTerm: LogsQuery['searchTerm']) => ({ searchTerm }),
        setSeverityLevels: (severityLevels: LogsQuery['severityLevels']) => ({ severityLevels }),
        setServiceNames: (serviceNames: LogsQuery['serviceNames']) => ({ serviceNames }),
        setLiveLogsCheckpoint: (liveLogsCheckpoint: string | null) => ({ liveLogsCheckpoint }),

        setFilterGroup: (filterGroup: UniversalFiltersGroup, openFilterOnInsert: boolean = true) => ({
            filterGroup,
            openFilterOnInsert,
        }),
        toggleAttributeBreakdown: (key: string) => ({ key }),
        setExpandedAttributeBreaksdowns: (expandedAttributeBreaksdowns: string[]) => ({ expandedAttributeBreaksdowns }),
        zoomDateRange: (multiplier: number) => ({ multiplier }),
        addFilter: (
            key: string,
            value: string,
            operator: PropertyOperator = PropertyOperator.Exact,
            propertyType: PropertyFilterType = PropertyFilterType.LogAttribute
        ) => ({
            key,
            value,
            operator,
            propertyType,
        }),
        togglePinLog: (logId: string) => ({ logId }),
        pinLog: (log: LogMessage) => ({ log }),
        unpinLog: (logId: string) => ({ logId }),
        setHighlightedLogId: (highlightedLogId: string | null) => ({ highlightedLogId }),
        setHasMoreLogsToLoad: (hasMoreLogsToLoad: boolean) => ({ hasMoreLogsToLoad }),
        setLogsPageSize: (logsPageSize: number) => ({ logsPageSize }),
        setInitialLogsLimit: (initialLogsLimit: number | null) => ({ initialLogsLimit }),
        copyLinkToLog: (logId: string) => ({ logId }),
        highlightNextLog: true,
        highlightPreviousLog: true,
        toggleExpandLog: (logId: string) => ({ logId }),
        setLiveTailRunning: (enabled: boolean) => ({ enabled }),
        setLiveTailInterval: (interval: number) => ({ interval }),
        pollForNewLogs: true,
        setLogs: (logs: LogMessage[]) => ({ logs }),
        setSparkline: (sparkline: any[]) => ({ sparkline }),
        setNextCursor: (nextCursor: string | null) => ({ nextCursor }),
        expireLiveTail: () => true,
        setLiveTailExpired: (liveTailExpired: boolean) => ({ liveTailExpired }),
        addLogsToSparkline: (logs: LogMessage[]) => logs,
    }),

    reducers({
        logsPageSize: [
            DEFAULT_LOGS_PAGE_SIZE,
            {
                setLogsPageSize: (_, { logsPageSize }) => logsPageSize,
            },
        ],
        initialLogsLimit: [
            DEFAULT_INITIAL_LOGS_LIMIT as number | null,
            {
                setInitialLogsLimit: (_, { initialLogsLimit }) => initialLogsLimit,
                fetchLogsSuccess: () => null,
            },
        ],
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
        liveLogsCheckpoint: [
            null as string | null,
            { persist: false },
            {
                setLiveLogsCheckpoint: (_, { liveLogsCheckpoint }) => liveLogsCheckpoint,
            },
        ],
        liveTailExpired: [
            true as boolean,
            { persist: false },
            {
                setLiveTailExpired: (_, { liveTailExpired }) => liveTailExpired,
                fetchLogsSuccess: () => false,
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
        liveTailAbortController: [
            null as AbortController | null,
            {
                setLiveTailAbortController: (_, { liveTailAbortController }) => liveTailAbortController,
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
                fetchNextLogsPage: () => true,
                fetchNextLogsPageSuccess: () => false,
                fetchNextLogsPageFailure: () => true,
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
        liveTailRunning: [
            false as boolean,
            {
                setLiveTailRunning: (_, { enabled }) => enabled,
                runQuery: () => false,
            },
        ],
        liveTailPollInterval: [
            DEFAULT_LIVE_TAIL_POLL_INTERVAL_MS as number,
            {
                setLiveTailInterval: (_, { interval }) => interval,
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
        nextCursor: [
            null as string | null,
            {
                setNextCursor: (_, { nextCursor }) => nextCursor,
                clearLogs: () => null,
            },
        ],
        expandedLogIds: [
            new Set<string>(),
            {
                toggleExpandLog: (state, { logId }) => {
                    const newSet = new Set(state)
                    if (newSet.has(logId)) {
                        newSet.delete(logId)
                    } else {
                        newSet.add(logId)
                    }
                    return newSet
                },
                clearLogs: () => new Set<string>(),
            },
        ],
    }),

    loaders(({ values, actions }) => ({
        logs: [
            [] as LogMessage[],
            {
                clearLogs: () => [],
                truncateLogs: ({ limit }) => values.logs.slice(0, limit),
                fetchLogs: async () => {
                    const logsController = new AbortController()
                    const signal = logsController.signal
                    actions.cancelInProgressLogs(logsController)

                    const response = await api.logs.query({
                        query: {
                            limit: values.initialLogsLimit ?? values.logsPageSize,
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
                    actions.setNextCursor(response.nextCursor ?? null)
                    parseLogAttributes(response.results)
                    return response.results
                },
                fetchNextLogsPage: async ({ limit }, breakpoint) => {
                    const logsController = new AbortController()
                    const signal = logsController.signal
                    actions.cancelInProgressLogs(logsController)

                    if (!values.nextCursor) {
                        return values.logs
                    }

                    await breakpoint(300)
                    const response = await api.logs.query({
                        query: {
                            limit: limit ?? values.logsPageSize,
                            orderBy: values.orderBy,
                            dateRange: values.utcDateRange,
                            searchTerm: values.searchTerm,
                            filterGroup: values.filterGroup as PropertyGroupFilter,
                            severityLevels: values.severityLevels,
                            serviceNames: values.serviceNames,
                            after: values.nextCursor,
                        },
                        signal,
                    })
                    actions.setLogsAbortController(null)
                    actions.setHasMoreLogsToLoad(!!response.hasMore)
                    actions.setNextCursor(response.nextCursor ?? null)
                    parseLogAttributes(response.results)
                    return [...values.logs, ...response.results]
                },
                setLogs: ({ logs }) => logs,
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
                setSparkline: ({ sparkline }) => sparkline,
            },
        ],
    })),

    selectors({
        tabId: [(_, p) => [p.tabId], (tabId: string) => tabId],
        liveTailDisabledReason: [
            (s) => [s.orderBy, s.dateRange, s.logsLoading, s.liveTailExpired],
            (
                orderBy: LogsQuery['orderBy'],
                dateRange: DateRange,
                logsLoading: boolean,
                liveTailExpired: boolean
            ): string | undefined => {
                if (orderBy !== 'latest') {
                    return 'Live tail only works with "Latest" ordering'
                }

                if (dateRange.date_to) {
                    return 'Live tail requires an open-ended time range'
                }

                if (logsLoading) {
                    return 'Wait for query to finish'
                }

                if (liveTailExpired) {
                    return 'Live tail has expired, run search again to live tail'
                }

                return undefined
            },
        ],
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
                const seen = new Set<string>()
                const result: ParsedLogMessage[] = []

                for (const log of logs) {
                    if (seen.has(log.uuid)) {
                        continue
                    }
                    seen.add(log.uuid)
                    const cleanBody = colors.unstyle(log.body)
                    let parsedBody: JsonType | null = null
                    try {
                        parsedBody = JSON.parse(cleanBody)
                    } catch {
                        // Not JSON, that's fine
                    }
                    result.push({ ...log, cleanBody, parsedBody })
                }

                return result
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
            (sparkline: any[]) => {
                let lastTime = ''
                let i = -1
                const labels: string[] = []
                const dates: string[] = []
                const data = Object.entries(
                    sparkline.reduce((accumulator, currentItem) => {
                        if (currentItem.time !== lastTime) {
                            labels.push(
                                humanFriendlyDetailedTime(currentItem.time, 'YYYY-MM-DD', 'HH:mm:ss', {
                                    timestampStyle: 'absolute',
                                })
                            )
                            dates.push(currentItem.time)
                            lastTime = currentItem.time
                            i++
                        }
                        const key = currentItem.level
                        if (!accumulator[key]) {
                            accumulator[key] = [...Array(sparkline.length)].map(() => 0)
                        }
                        accumulator[key][i] += currentItem.count
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
        totalLogsMatchingFilters: [
            (s) => [s.sparkline],
            (sparkline): number => sparkline.reduce((sum, item) => sum + item.count, 0),
        ],
        logsRemainingToLoad: [
            (s) => [s.totalLogsMatchingFilters, s.logs],
            (totalLogsMatchingFilters, logs): number => totalLogsMatchingFilters - logs.length,
        ],
    }),

    listeners(({ values, actions, cache }) => ({
        fetchLogsFailure: ({ error }) => {
            const errorStr = String(error).toLowerCase()
            if (error !== NEW_QUERY_STARTED_ERROR_MESSAGE && !errorStr.includes('abort')) {
                lemonToast.error(`Failed to load logs: ${error}`)
            }
        },
        fetchNextLogsPageFailure: ({ error }) => {
            const errorStr = String(error).toLowerCase()
            if (error !== NEW_QUERY_STARTED_ERROR_MESSAGE && !errorStr.includes('abort')) {
                lemonToast.error(`Failed to load more logs: ${error}`)
            }
        },
        runQuery: async ({ debounce }, breakpoint) => {
            if (debounce) {
                await breakpoint(debounce)
            }
            actions.clearLogs()
            actions.fetchLogs()
            actions.fetchSparkline()
            actions.cancelInProgressLiveTail(null)
        },
        cancelInProgressLogs: ({ logsAbortController }) => {
            if (values.logsAbortController !== null) {
                values.logsAbortController.abort(NEW_QUERY_STARTED_ERROR_MESSAGE)
            }
            actions.setLogsAbortController(logsAbortController)
        },
        cancelInProgressSparkline: ({ sparklineAbortController }) => {
            if (values.sparklineAbortController !== null) {
                values.sparklineAbortController.abort(NEW_QUERY_STARTED_ERROR_MESSAGE)
            }
            actions.setSparklineAbortController(sparklineAbortController)
        },
        cancelInProgressLiveTail: ({ liveTailAbortController }) => {
            if (values.liveTailAbortController !== null) {
                values.liveTailAbortController.abort('live tail request cancelled')
            }
            actions.setLiveTailAbortController(liveTailAbortController)
            cache.disposables.dispose('liveTailTimer')
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
        expireLiveTail: async ({}, breakpoint) => {
            await breakpoint(30000)
            if (values.liveTailRunning) {
                return
            }
            actions.setLiveTailExpired(true)
        },
        addFilter: ({
            key,
            value,
            operator,
            propertyType,
        }: {
            key: string
            value: string
            operator: string
            propertyType: PropertyFilterType
        }) => {
            const currentGroup = values.filterGroup.values[0] as UniversalFiltersGroup

            const newGroup: UniversalFiltersGroup = {
                ...currentGroup,
                values: [
                    ...currentGroup.values,
                    {
                        key,
                        value: [value],
                        operator,
                        type: propertyType,
                    } as UniversalFiltersGroupValue,
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
        applyLogsPageSize: ({ logsPageSize }) => {
            const currentCount = values.logs.length

            if (logsPageSize > currentCount && values.hasMoreLogsToLoad) {
                actions.fetchNextLogsPage(logsPageSize - currentCount)
            } else if (logsPageSize < currentCount) {
                actions.truncateLogs(logsPageSize)
                actions.setHasMoreLogsToLoad(true)
            }
        },
        highlightNextLog: () => {
            const logs = values.parsedLogs
            if (logs.length === 0) {
                return
            }

            const currentIndex = values.highlightedLogId
                ? logs.findIndex((log) => log.uuid === values.highlightedLogId)
                : -1

            if (currentIndex === -1) {
                actions.setHighlightedLogId(logs[0].uuid)
            } else if (currentIndex < logs.length - 1) {
                actions.setHighlightedLogId(logs[currentIndex + 1].uuid)
            } else if (values.hasMoreLogsToLoad && !values.logsLoading) {
                actions.fetchNextLogsPage()
            }
        },
        highlightPreviousLog: () => {
            const logs = values.parsedLogs
            if (logs.length === 0) {
                return
            }

            const currentIndex = values.highlightedLogId
                ? logs.findIndex((log) => log.uuid === values.highlightedLogId)
                : -1

            if (currentIndex === -1) {
                actions.setHighlightedLogId(logs[logs.length - 1].uuid)
            } else if (currentIndex > 0) {
                actions.setHighlightedLogId(logs[currentIndex - 1].uuid)
            }
        },
        setLiveTailRunning: async ({ enabled }) => {
            if (enabled) {
                actions.pollForNewLogs()
            } else {
                actions.cancelInProgressLiveTail(null)
                actions.expireLiveTail()
            }
        },
        pollForNewLogs: async () => {
            if (!values.liveTailRunning || values.orderBy !== 'latest' || document.hidden) {
                return
            }

            const liveTailController = new AbortController()
            const signal = liveTailController.signal
            actions.cancelInProgressLiveTail(liveTailController)
            let duration = 0

            try {
                const start = Date.now()
                const response = await api.logs.query({
                    query: {
                        limit: values.logsPageSize,
                        orderBy: values.orderBy,
                        dateRange: values.utcDateRange,
                        searchTerm: values.searchTerm,
                        filterGroup: values.filterGroup as PropertyGroupFilter,
                        severityLevels: values.severityLevels,
                        serviceNames: values.serviceNames,
                        liveLogsCheckpoint: values.liveLogsCheckpoint ?? undefined,
                    },
                    signal,
                })
                duration = Date.now() - start

                if (response.results.length > 0) {
                    // the live_logs_checkpoint is the latest known timestamp for which we know we have all logs up to that point
                    // it's returned from clickhouse as a value on every log row - but the value is fixed per query
                    actions.setLiveLogsCheckpoint(response.results[0].live_logs_checkpoint ?? null)
                }

                response.results.forEach((row) => {
                    Object.keys(row.attributes).forEach((key) => {
                        const value = row.attributes[key]
                        row.attributes[key] = typeof value === 'string' ? value : JSON.stringify(value)
                    })
                })

                const existingUuids = new Set(values.logs.map((log) => log.uuid))
                const newLogs = response.results.filter((log) => !existingUuids.has(log.uuid))

                if (newLogs.length > 0) {
                    actions.setLiveTailInterval(DEFAULT_LIVE_TAIL_POLL_INTERVAL_MS)
                    actions.setLogs(
                        [
                            ...newLogs.map((log) => ({ ...log, new: true })),
                            ...values.logs.map((log) => ({ ...log, new: false })),
                        ]
                            .sort((a, b) => Date.parse(b.timestamp) - Date.parse(a.timestamp))
                            .slice(0, values.logsPageSize)
                    )
                    actions.addLogsToSparkline(newLogs)
                } else {
                    const newInterval = Math.min(
                        values.liveTailPollInterval * 1.5,
                        DEFAULT_LIVE_TAIL_POLL_INTERVAL_MAX_MS
                    )
                    actions.setLiveTailInterval(newInterval)
                }
            } catch (error) {
                if (signal.aborted) {
                    return
                }
                console.error('Live tail polling error:', error)
                actions.setLiveTailRunning(false)
            } finally {
                actions.setLiveTailAbortController(null)
                if (values.liveTailRunning) {
                    cache.disposables.add(() => {
                        const timerId = setTimeout(
                            () => {
                                actions.pollForNewLogs()
                            },
                            Math.max(duration, values.liveTailPollInterval)
                        )
                        return () => clearTimeout(timerId)
                    }, 'liveTailTimer')
                }
            }
        },
        // insert logs into the sparkline data
        addLogsToSparkline: (logs: LogMessage[]) => {
            // if the sparkline hasn't loaded do nothing.
            if (!values.sparkline || values.sparkline.length < 2) {
                return
            }

            const first_bucket = values.sparklineData.dates[0]
            const last_bucket = values.sparklineData.dates[values.sparklineData.dates.length - 1]
            const sparklineTimeWindow = dayjs(last_bucket).diff(first_bucket, 'seconds')
            const interval = dayjs(values.sparklineData.dates[1]).diff(first_bucket, 'seconds')
            let latest_time_bucket = dayjs(last_bucket)

            const sparklineMap: Map<string, { time: string; level: string; count: number }> = new Map()

            for (const bucket of values.sparkline) {
                const key = `${dayjs(bucket.time).toISOString()}_${bucket.level}`
                sparklineMap.set(key, { ...bucket })
            }

            for (const log of logs) {
                const time_bucket = dayjs.unix(Math.floor(dayjs(log.timestamp).unix() / interval) * interval)
                if (time_bucket.isAfter(latest_time_bucket)) {
                    latest_time_bucket = time_bucket
                }
                const key = `${time_bucket.toISOString()}_${log.level}`
                if (sparklineMap.has(key)) {
                    sparklineMap.get(key)!.count += 1
                } else {
                    sparklineMap.set(key, { time: time_bucket.toISOString(), level: log.level, count: 1 })
                }
            }
            actions.setSparkline(
                Array.from(sparklineMap.values())
                    .sort((a, b) => dayjs(a.time).diff(dayjs(b.time)) || a.level.localeCompare(b.level))
                    .filter((item) => latest_time_bucket.diff(dayjs(item.time), 'seconds') <= sparklineTimeWindow)
            )
        },
        copyLinkToLog: ({ logId }: { logId: string }) => {
            const url = new URL(window.location.href)
            url.searchParams.set('highlightedLogId', logId)
            if (values.visibleLogsTimeRange) {
                url.searchParams.set(
                    'dateRange',
                    JSON.stringify({
                        date_from: values.visibleLogsTimeRange.date_from,
                        date_to: values.visibleLogsTimeRange.date_to,
                        explicitDate: true,
                    })
                )
            }
            if (values.logs.length > 0) {
                url.searchParams.set('initialLogsLimit', String(values.logs.length))
            }
            void copyToClipboard(url.toString(), 'link to log')
        },
    })),

    events(({ values, actions }) => ({
        beforeUnmount: () => {
            actions.setLiveTailRunning(false)
            actions.cancelInProgressLiveTail(null)
            if (values.logsAbortController) {
                values.logsAbortController.abort('unmounting component')
            }
            if (values.sparklineAbortController) {
                values.sparklineAbortController.abort('unmounting component')
            }
        },
    })),

    afterMount(({ values, actions }) => {
        if (values.parsedLogs.length === 0) {
            actions.runQuery()
        }
    }),
])
