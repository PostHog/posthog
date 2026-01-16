import colors from 'ansi-colors'
import equal from 'fast-deep-equal'
import { actions, afterMount, connect, events, kea, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'
import { syncSearchParams, updateSearchParams } from '@posthog/products-error-tracking/frontend/utils'

import api from 'lib/api'
import { dataColorVars } from 'lib/colors'
import { DEFAULT_UNIVERSAL_GROUP_FILTER } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { dayjs } from 'lib/dayjs'
import { tabAwareActionToUrl } from 'lib/logic/scenes/tabAwareActionToUrl'
import { tabAwareScene } from 'lib/logic/scenes/tabAwareScene'
import { tabAwareUrlToAction } from 'lib/logic/scenes/tabAwareUrlToAction'
import { humanFriendlyDetailedTime, parseTagsFilter } from 'lib/utils'
import { Params } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'

import {
    DateRange,
    LogMessage,
    LogSeverityLevel,
    LogsQuery,
    LogsSparklineBreakdownBy,
    ProductIntentContext,
    ProductKey,
} from '~/queries/schema/schema-general'
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
import { LogsFilters, LogsFiltersHistoryEntry, LogsOrderBy, ParsedLogMessage } from './types'

const DEFAULT_DATE_RANGE = { date_from: '-1h', date_to: null }
const VALID_SEVERITY_LEVELS: readonly LogSeverityLevel[] = ['trace', 'debug', 'info', 'warn', 'error', 'fatal']
const DEFAULT_SEVERITY_LEVELS = [] as LogsQuery['severityLevels']

const isValidSeverityLevel = (level: string): level is LogSeverityLevel =>
    VALID_SEVERITY_LEVELS.includes(level as LogSeverityLevel)
const DEFAULT_SERVICE_NAMES = [] as LogsQuery['serviceNames']
const DEFAULT_HIGHLIGHTED_LOG_ID = null as string | null
const DEFAULT_ORDER_BY = 'latest' as LogsQuery['orderBy']
const DEFAULT_LOGS_PAGE_SIZE: number = 250
const DEFAULT_INITIAL_LOGS_LIMIT = null as number | null
const NEW_QUERY_STARTED_ERROR_MESSAGE = 'new query started' as const
const DEFAULT_LIVE_TAIL_POLL_INTERVAL_MS = 1000
const DEFAULT_LIVE_TAIL_POLL_INTERVAL_MAX_MS = 5000

const DEFAULT_SPARKLINE_BREAKDOWN_BY: LogsSparklineBreakdownBy = 'severity'

const stringifyLogAttributes = (attributes: Record<string, any>): Record<string, string> => {
    const result: Record<string, string> = {}
    for (const key of Object.keys(attributes)) {
        const value = attributes[key]
        result[key] = typeof value === 'string' ? value : JSON.stringify(value)
    }
    return result
}

export interface LogsLogicProps {
    tabId: string
}

export const logsLogic = kea<logsLogicType>([
    props({} as LogsLogicProps),
    path(['products', 'logs', 'frontend', 'logsLogic']),
    tabAwareScene(),
    connect(() => ({
        actions: [teamLogic, ['addProductIntent']],
    })),
    tabAwareUrlToAction(({ actions, values }) => {
        const urlToAction = (_: any, params: Params): void => {
            const filtersFromUrl: Partial<LogsFilters> = {}
            let hasFilterChanges = false

            if (params.dateRange) {
                try {
                    const dateRange =
                        typeof params.dateRange === 'string' ? JSON.parse(params.dateRange) : params.dateRange
                    if (!equal(dateRange, values.dateRange)) {
                        filtersFromUrl.dateRange = dateRange
                        hasFilterChanges = true
                    }
                } catch {
                    // Ignore malformed dateRange JSON in URL
                }
            }
            if (params.filterGroup && !equal(params.filterGroup, values.filterGroup)) {
                filtersFromUrl.filterGroup = params.filterGroup
                hasFilterChanges = true
            }
            if (params.searchTerm && !equal(params.searchTerm, values.searchTerm)) {
                filtersFromUrl.searchTerm = params.searchTerm
                hasFilterChanges = true
            }
            if (params.severityLevels) {
                const parsed = parseTagsFilter(params.severityLevels)
                if (parsed) {
                    const levels = parsed.filter(isValidSeverityLevel)
                    if (levels.length > 0 && !equal(levels, values.severityLevels)) {
                        filtersFromUrl.severityLevels = levels
                        hasFilterChanges = true
                    }
                }
            }
            if (params.serviceNames) {
                const names = parseTagsFilter(params.serviceNames)
                if (names && !equal(names, values.serviceNames)) {
                    filtersFromUrl.serviceNames = names
                    hasFilterChanges = true
                }
            }

            if (hasFilterChanges) {
                actions.setFiltersFromUrl(filtersFromUrl)
            }

            // Non-filter params handled separately
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
            syncUrlAndRunQuery: () => buildUrlAndRunQuery(),
            syncUrlWithPageSize: () => updateUrlWithPageSize(),
            syncUrlWithHighlight: () => updateHighlightURL(),
        }
    }),

    actions({
        syncUrlAndRunQuery: true,
        syncUrlWithPageSize: true,
        syncUrlWithHighlight: true,
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
        setFilters: (filters: Partial<LogsFilters>, pushToHistory: boolean = true) => ({ filters, pushToHistory }),
        setFiltersFromUrl: (filters: Partial<LogsFilters>) => ({ filters }),
        pushToFilterHistory: (filters: LogsFilters) => ({ filters }),
        restoreFiltersFromHistory: (index: number) => ({ index }),
        clearFilterHistory: true,
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
        setSparklineBreakdownBy: (sparklineBreakdownBy: LogsSparklineBreakdownBy) => ({ sparklineBreakdownBy }),
    }),

    reducers({
        filterHistory: [
            [] as LogsFiltersHistoryEntry[],
            { persist: true },
            {
                pushToFilterHistory: (state, { filters }) => {
                    if (state.length > 0 && equal(state[0].filters, filters)) {
                        return state
                    }
                    const entry: LogsFiltersHistoryEntry = { filters, timestamp: Date.now() }
                    return [entry, ...state].slice(0, 10)
                },
                clearFilterHistory: () => [],
            },
        ],
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
                setFilters: (state, { filters }) => filters.dateRange ?? state,
                setFiltersFromUrl: (state, { filters }) => filters.dateRange ?? state,
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
                setFilters: (state, { filters }) => filters.searchTerm ?? state,
                setFiltersFromUrl: (state, { filters }) => filters.searchTerm ?? state,
            },
        ],
        severityLevels: [
            DEFAULT_SEVERITY_LEVELS,
            {
                setSeverityLevels: (_, { severityLevels }) => severityLevels,
                setFilters: (state, { filters }) => filters.severityLevels ?? state,
                setFiltersFromUrl: (state, { filters }) => filters.severityLevels ?? state,
            },
        ],
        serviceNames: [
            DEFAULT_SERVICE_NAMES,
            {
                setServiceNames: (_, { serviceNames }) => serviceNames,
                setFilters: (state, { filters }) => filters.serviceNames ?? state,
                setFiltersFromUrl: (state, { filters }) => filters.serviceNames ?? state,
            },
        ],
        filterGroup: [
            DEFAULT_UNIVERSAL_GROUP_FILTER,
            {
                setFilterGroup: (_, { filterGroup }) =>
                    filterGroup && filterGroup.values ? filterGroup : DEFAULT_UNIVERSAL_GROUP_FILTER,
                setFilters: (state, { filters }) =>
                    filters.filterGroup && filters.filterGroup.values ? filters.filterGroup : state,
                setFiltersFromUrl: (state, { filters }) =>
                    filters.filterGroup && filters.filterGroup.values ? filters.filterGroup : state,
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
        sparklineBreakdownBy: [
            DEFAULT_SPARKLINE_BREAKDOWN_BY as LogsSparklineBreakdownBy,
            { persist: true },
            {
                setSparklineBreakdownBy: (_, { sparklineBreakdownBy }) => sparklineBreakdownBy,
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
                            sparklineBreakdownBy: values.sparklineBreakdownBy,
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
        filters: [
            (s) => [s.dateRange, s.searchTerm, s.severityLevels, s.serviceNames, s.filterGroup],
            (
                dateRange: LogsFilters['dateRange'],
                searchTerm: LogsFilters['searchTerm'],
                severityLevels: LogsFilters['severityLevels'],
                serviceNames: LogsFilters['serviceNames'],
                filterGroup: LogsFilters['filterGroup']
            ): LogsFilters => ({
                dateRange,
                searchTerm,
                severityLevels,
                serviceNames,
                filterGroup,
            }),
        ],
        hasFilterHistory: [
            (s) => [s.filterHistory],
            (filterHistory: LogsFiltersHistoryEntry[]) => filterHistory.length > 0,
        ],
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
                    result.push({
                        ...log,
                        attributes: stringifyLogAttributes(log.attributes),
                        cleanBody,
                        parsedBody,
                        originalLog: log,
                    })
                }

                return result
            },
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
            (s) => [s.sparkline, s.sparklineBreakdownBy],
            (sparkline: any[], sparklineBreakdownBy: LogsSparklineBreakdownBy) => {
                const breakdownKey = sparklineBreakdownBy

                let lastTime = ''
                let i = -1
                const labels: string[] = []
                const dates: string[] = []
                const accumulated = sparkline.reduce(
                    (accumulator, currentItem) => {
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
                        const key = currentItem[breakdownKey]
                        if (!key) {
                            return accumulator
                        }
                        if (!accumulator[key]) {
                            accumulator[key] = []
                        }
                        while (accumulator[key].length <= i) {
                            accumulator[key].push(0)
                        }
                        accumulator[key][i] += currentItem.count
                        return accumulator
                    },
                    {} as Record<string, number[]>
                )

                const data = Object.entries(accumulated)
                    .sort(([a], [b]) => a.localeCompare(b))
                    .map(([name, values], index) => ({
                        name,
                        values: values as number[],
                        color:
                            sparklineBreakdownBy === 'service'
                                ? dataColorVars[index % dataColorVars.length]
                                : {
                                      fatal: 'danger-dark',
                                      error: 'danger',
                                      warn: 'warning',
                                      info: 'brand-blue',
                                      debug: 'muted',
                                      trace: 'muted-alt',
                                  }[name],
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
        fetchLogsSuccess: ({ logs }) => {
            if (logs.length === 0) {
                posthog.capture('logs no results returned')
            } else {
                posthog.capture('logs results returned', { count: logs.length })
            }
        },
        fetchNextLogsPage: () => {
            posthog.capture('logs load more requested')
        },
        setSearchTerm: ({ searchTerm }) => {
            if (values.hasRunQuery) {
                posthog.capture('logs filter changed', {
                    filter_type: 'search',
                    search_term_length: searchTerm?.length ?? 0,
                })
                actions.addProductIntent({
                    product_type: ProductKey.LOGS,
                    intent_context: ProductIntentContext.LOGS_SET_FILTERS,
                })
                actions.pushToFilterHistory(values.filters)
            }
            actions.syncUrlAndRunQuery()
        },
        setFilterGroup: () => {
            // Don't run query if there's a filter without a value (user is still selecting)
            const hasIncompleteUniversalFilterValue = (filterValue: UniversalFiltersGroupValue): boolean => {
                if (!filterValue || typeof filterValue !== 'object') {
                    return false
                }

                // If this is a nested UniversalFiltersGroup, recursively check its values
                if ('type' in filterValue && 'values' in filterValue) {
                    const groupValues = (filterValue as UniversalFiltersGroup).values ?? []
                    return groupValues.some((child) => hasIncompleteUniversalFilterValue(child))
                }

                // ActionFilter: check for missing id
                if ('id' in filterValue) {
                    return (filterValue as { id: unknown }).id == null
                }

                // Property filter: check for missing or empty value
                if ('value' in filterValue) {
                    const val = (filterValue as { value: unknown }).value
                    return val == null || (Array.isArray(val) && val.length === 0)
                }

                return false
            }

            const rootGroup = values.filterGroup?.values?.[0] as UniversalFiltersGroup | undefined
            const hasIncompleteFilter =
                rootGroup?.values?.some((filterValue) => hasIncompleteUniversalFilterValue(filterValue)) ?? false

            if (hasIncompleteFilter) {
                return
            }

            if (values.hasRunQuery) {
                posthog.capture('logs filter changed', { filter_type: 'attributes' })
                actions.addProductIntent({
                    product_type: ProductKey.LOGS,
                    intent_context: ProductIntentContext.LOGS_SET_FILTERS,
                })
                actions.pushToFilterHistory(values.filters)
            }
            actions.syncUrlAndRunQuery()
        },
        setSeverityLevels: ({ severityLevels }) => {
            if (values.hasRunQuery) {
                posthog.capture('logs filter changed', {
                    filter_type: 'severity',
                    severity_levels: severityLevels ?? [],
                })
                actions.addProductIntent({
                    product_type: ProductKey.LOGS,
                    intent_context: ProductIntentContext.LOGS_SET_FILTERS,
                })
                actions.pushToFilterHistory(values.filters)
            }
            actions.syncUrlAndRunQuery()
        },
        setServiceNames: ({ serviceNames }) => {
            if (values.hasRunQuery) {
                posthog.capture('logs filter changed', {
                    filter_type: 'service',
                    service_count: serviceNames?.length ?? 0,
                })
                actions.addProductIntent({
                    product_type: ProductKey.LOGS,
                    intent_context: ProductIntentContext.LOGS_SET_FILTERS,
                })
                actions.pushToFilterHistory(values.filters)
            }
            actions.syncUrlAndRunQuery()
        },
        setDateRange: () => {
            if (values.hasRunQuery) {
                posthog.capture('logs filter changed', { filter_type: 'date_range' })
                actions.addProductIntent({
                    product_type: ProductKey.LOGS,
                    intent_context: ProductIntentContext.LOGS_SET_FILTERS,
                })
                actions.pushToFilterHistory(values.filters)
            }
            actions.syncUrlAndRunQuery()
        },
        setFilters: ({ pushToHistory }) => {
            if (values.hasRunQuery) {
                posthog.capture('logs filter changed', { filter_type: 'bulk' })
                actions.addProductIntent({
                    product_type: ProductKey.LOGS,
                    intent_context: ProductIntentContext.LOGS_SET_FILTERS,
                })
                if (pushToHistory) {
                    actions.pushToFilterHistory(values.filters)
                }
            }
            actions.syncUrlAndRunQuery()
        },
        setOrderBy: () => {
            actions.syncUrlAndRunQuery()
        },
        setLogsPageSize: () => {
            actions.syncUrlWithPageSize()
        },
        setHighlightedLogId: () => {
            actions.syncUrlWithHighlight()
        },
        setLiveTailRunning: async ({ enabled }) => {
            if (enabled) {
                posthog.capture('logs live tail started')
                actions.pollForNewLogs()
            } else {
                actions.cancelInProgressLiveTail(null)
                actions.expireLiveTail()
            }
        },
        runQuery: async ({ debounce }, breakpoint) => {
            if (debounce) {
                await breakpoint(debounce)
            }
            // Track query execution (skip initial page load)
            if (values.hasRunQuery) {
                posthog.capture('logs query executed', {
                    has_search_term: !!values.searchTerm,
                    has_filters: values.filterGroup.values.length > 0,
                    severity_count: values.severityLevels?.length ?? 0,
                    service_count: values.serviceNames?.length ?? 0,
                })
            }
            actions.clearLogs()
            actions.fetchLogs()
            actions.fetchSparkline()
            actions.cancelInProgressLiveTail(null)
        },
        setFiltersFromUrl: () => {
            actions.runQuery()
        },
        restoreFiltersFromHistory: ({ index }) => {
            const entry = values.filterHistory[index]
            if (entry) {
                posthog.capture('logs filter history restored', {
                    history_index: index,
                    history_size: values.filterHistory.length,
                })
                actions.setFilters(entry.filters, false)
            }
        },
        clearFilterHistory: () => {
            posthog.capture('logs filter history cleared', {
                history_size: values.filterHistory.length,
            })
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
        setSparklineBreakdownBy: () => {
            actions.fetchSparkline()
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
        // insert logs into the sparkline data (only works for severity breakdown)
        addLogsToSparkline: (logs: LogMessage[]) => {
            // Only update incrementally for severity breakdown - service would need service_name from logs
            if (values.sparklineBreakdownBy !== 'severity') {
                return
            }
            // if the sparkline hasn't loaded do nothing.
            if (!values.sparkline || values.sparkline.length < 2) {
                return
            }

            const first_bucket = values.sparklineData.dates[0]
            const last_bucket = values.sparklineData.dates[values.sparklineData.dates.length - 1]
            const sparklineTimeWindow = dayjs(last_bucket).diff(first_bucket, 'seconds')
            const interval = dayjs(values.sparklineData.dates[1]).diff(first_bucket, 'seconds')
            let latest_time_bucket = dayjs(last_bucket)

            const sparklineMap: Map<string, { time: string; severity: string; count: number }> = new Map()

            for (const bucket of values.sparkline) {
                const key = `${dayjs(bucket.time).toISOString()}_${bucket.severity}`
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
                    sparklineMap.set(key, { time: time_bucket.toISOString(), severity: log.level, count: 1 })
                }
            }
            actions.setSparkline(
                Array.from(sparklineMap.values())
                    .sort((a, b) => dayjs(a.time).diff(dayjs(b.time)) || a.severity.localeCompare(b.severity))
                    .filter((item) => latest_time_bucket.diff(dayjs(item.time), 'seconds') <= sparklineTimeWindow)
            )
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
