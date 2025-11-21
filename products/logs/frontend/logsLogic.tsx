import colors from 'ansi-colors'
import equal from 'fast-deep-equal'
import { actions, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { syncSearchParams, updateSearchParams } from '@posthog/products-error-tracking/frontend/utils'

import api from 'lib/api'
import { DEFAULT_UNIVERSAL_GROUP_FILTER } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { Dayjs, dayjs } from 'lib/dayjs'
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
const DEFAULT_LOG_LIMIT = 100
const DEFAULT_LIVE_TAIL_POLL_INTERVAL_MS = 1000
const DEFAULT_LIVE_TAIL_POLL_INTERVAL_MAX_MS = 5000

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
        cancelInProgressLiveTail: (liveTailAbortController: AbortController | null) => ({ liveTailAbortController }),
        setLogsAbortController: (logsAbortController: AbortController | null) => ({ logsAbortController }),
        setSparklineAbortController: (sparklineAbortController: AbortController | null) => ({
            sparklineAbortController,
        }),
        setLiveTailAbortController: (liveTailAbortController: AbortController | null) => ({
            liveTailAbortController,
        }),
        setDateRange: (dateRange: DateRange) => ({ dateRange }),
        setOrderBy: (orderBy: LogsQuery['orderBy']) => ({ orderBy }),
        setSearchTerm: (searchTerm: LogsQuery['searchTerm']) => ({ searchTerm }),
        setSeverityLevels: (severityLevels: LogsQuery['severityLevels']) => ({ severityLevels }),
        setServiceNames: (serviceNames: LogsQuery['serviceNames']) => ({ serviceNames }),
        setWrapBody: (wrapBody: boolean) => ({ wrapBody }),
        setPrettifyJson: (prettifyJson: boolean) => ({ prettifyJson }),
        setLiveLogsCheckpoint: (liveLogsCheckpoint: string) => ({ liveLogsCheckpoint }),
        setLastSparklineUpdate: (lastSparklineUpdate: Dayjs) => ({ lastSparklineUpdate }),
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
        setLiveTailRunning: (enabled: boolean) => ({ enabled }),
        setLiveTailInterval: (interval: number) => ({ interval }),
        pollForNewLogs: true,
        setLogs: (logs: LogMessage[]) => ({ logs }),
        setSparkline: (sparkline: any[]) => ({ sparkline }),
        expireLiveTail: () => true,
        setLiveTailExpired: (liveTailExpired: boolean) => ({ liveTailExpired }),
        addLogsToSparkline: (logs: LogMessage[]) => logs,
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
        sparkline: [
            [] as any[],
            {
                setSparkline: (_, { sparkline }) => sparkline,
            },
        ],
    }),

    loaders(({ values, actions }) => ({
        logs: {
            __default: [] as LogMessage[],
            fetchLogs: async () => {
                const logsController = new AbortController()
                const signal = logsController.signal
                actions.cancelInProgressLogs(logsController)

                const response = await api.logs.query({
                    query: {
                        limit: DEFAULT_LOG_LIMIT,
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
                // expire live tail has a 30 second delay
                actions.expireLiveTail()
                if (response.results.length > 0) {
                    // the live_logs_checkpoint is the latest known timestamp for which we know we have all logs up to that point
                    // it's returned from clickhouse as a value on every log row - but the value is fixed per query
                    actions.setLiveLogsCheckpoint(response.results[0].live_logs_checkpoint)
                }
                response.results.forEach((row) => {
                    Object.keys(row.attributes).forEach((key) => {
                        const value = row.attributes[key]
                        row.attributes[key] = typeof value === 'string' ? value : JSON.stringify(value)
                    })
                })
                return response.results
            },
            setLogs: ({ logs }) => logs,
        },
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

    selectors(() => ({
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
                                    showNow: false,
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
    })),

    listeners(({ values, actions, cache }) => ({
        runQuery: async ({ debounce }, breakpoint) => {
            if (debounce) {
                await breakpoint(debounce)
            }
            actions.fetchLogs()
            actions.fetchSparkline()
            actions.cancelInProgressLiveTail(null)
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
        expireLiveTail: async ({}, breakpoint) => {
            await breakpoint(30000)
            if (values.liveTailRunning) {
                return
            }
            actions.setLiveTailExpired(true)
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
                        limit: DEFAULT_LOG_LIMIT,
                        orderBy: values.orderBy,
                        dateRange: values.utcDateRange,
                        searchTerm: values.searchTerm,
                        filterGroup: values.filterGroup as PropertyGroupFilter,
                        severityLevels: values.severityLevels,
                        serviceNames: values.serviceNames,
                        liveLogsCheckpoint: values.liveLogsCheckpoint,
                    },
                    signal,
                })
                duration = Date.now() - start

                if (response.results.length > 0) {
                    // the live_logs_checkpoint is the latest known timestamp for which we know we have all logs up to that point
                    // it's returned from clickhouse as a value on every log row - but the value is fixed per query
                    actions.setLiveLogsCheckpoint(response.results[0].live_logs_checkpoint)
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
                            .slice(0, DEFAULT_LOG_LIMIT)
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
                            Math.min(duration, values.liveTailPollInterval)
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
            const duration = dayjs(last_bucket).diff(first_bucket, 'seconds')
            const interval = dayjs(values.sparklineData.dates[1]).diff(first_bucket, 'seconds')
            let latest_time_bucket = dayjs(last_bucket)
            for (const log of logs) {
                const time_bucket = dayjs.unix(Math.floor(dayjs(log.timestamp).unix() / interval) * interval)
                if (time_bucket.isAfter(latest_time_bucket)) {
                    latest_time_bucket = time_bucket
                }
                // insert all new logs into the sparkline data as their own bucket - we'll later aggregate them
                values.sparkline.push({ time: time_bucket.toISOString(), level: log.level, count: 1 })
            }
            actions.setSparkline(
                values.sparkline
                    .sort(
                        // sort buckets by time, then level
                        (a, b) => dayjs(a.time).diff(dayjs(b.time)) || a.level.localeCompare(b.level)
                    )
                    .reduce((acc, curr) => {
                        // aggregate buckets by time and level
                        const index = acc.findIndex(
                            (item) => dayjs(item.time).isSame(dayjs(curr.time)) && item.level === curr.level
                        )
                        if (index === -1) {
                            // haven't seen this time/level combo before, add it to the accumulator
                            acc.push(curr)
                        } else {
                            // increase existing bucket
                            acc[index].count += curr.count
                        }
                        return acc
                        // Keep the overall sparkline time range the same by dropping older buckets
                    }, [])
                    .filter((item) => latest_time_bucket.diff(dayjs(item.time), 'seconds') <= duration)
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
])
