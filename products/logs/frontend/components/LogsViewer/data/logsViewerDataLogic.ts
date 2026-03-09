import colors from 'ansi-colors'
import { actions, afterMount, connect, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { dataColorVars } from 'lib/colors'
import { SetupTaskId, globalSetupLogic } from 'lib/components/ProductSetup'
import { dayjs } from 'lib/dayjs'
import { humanFriendlyDetailedTime } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'

import { LogMessage, LogsQuery, LogsSparklineBreakdownBy } from '~/queries/schema/schema-general'
import { integer } from '~/queries/schema/type-utils'
import { JsonType, PropertyGroupFilter } from '~/types'

import { logsViewerConfigLogic } from 'products/logs/frontend/components/LogsViewer/config/logsViewerConfigLogic'
import { LogsViewerFilters } from 'products/logs/frontend/components/LogsViewer/config/types'
import { logsViewerFiltersLogic } from 'products/logs/frontend/components/LogsViewer/Filters/logsViewerFiltersLogic'

// TODO: Move to ./types.ts
import { ParsedLogMessage } from '../../../types'
import type { logsViewerDataLogicType } from './logsViewerDataLogicType'

const DEFAULT_LIVE_TAIL_POLL_INTERVAL_MS = 1000
const DEFAULT_LOGS_PAGE_SIZE: number = 250
export const DEFAULT_INITIAL_LOGS_LIMIT = null as number | null
const NEW_QUERY_STARTED_ERROR_MESSAGE = 'new query started' as const
const DEFAULT_LIVE_TAIL_POLL_INTERVAL_MAX_MS = 5000

function classifyQueryError(error: unknown): { error_type: string; status_code: number | null } {
    const errorStr = String(error).toLowerCase()
    const statusCode =
        typeof error === 'object' && error !== null && 'status' in error ? (error.status as number) : null

    if (statusCode === 504 || errorStr.includes('timed out') || errorStr.includes('timeout')) {
        return { error_type: 'timeout', status_code: statusCode }
    }
    if (errorStr.includes('memory limit') || errorStr.includes('out of memory')) {
        return { error_type: 'out_of_memory', status_code: statusCode }
    }
    if (statusCode === 429) {
        return { error_type: 'rate_limited', status_code: statusCode }
    }
    if (statusCode !== null && statusCode >= 500) {
        return { error_type: 'server_error', status_code: statusCode }
    }
    return { error_type: 'unknown', status_code: statusCode }
}

function isUserInitiatedError(error: unknown): boolean {
    const errorStr = String(error).toLowerCase()
    return error === NEW_QUERY_STARTED_ERROR_MESSAGE || errorStr.includes('abort')
}

const stringifyLogAttributes = (attributes: Record<string, any>): Record<string, string> => {
    const result: Record<string, string> = {}
    for (const attributeKey of Object.keys(attributes)) {
        const value = attributes[attributeKey]
        result[attributeKey] = typeof value === 'string' ? value : JSON.stringify(value)
    }
    return result
}

export interface LogsViewerDataLogicProps {
    id: string
    autoLoad?: boolean
}

export const logsViewerDataLogic = kea<logsViewerDataLogicType>([
    props({ id: 'default', autoLoad: true } as LogsViewerDataLogicProps),
    path(['products', 'logs', 'frontend', 'components', 'LogsViewer', 'data', 'logsViewerDataLogic']),
    key((props) => props.id),
    connect(({ id }: LogsViewerDataLogicProps) => ({
        actions: [
            teamLogic,
            ['addProductIntent'],
            logsViewerFiltersLogic({ id }),
            ['setDateRange', 'setFilterGroup', 'setFilters', 'setSearchTerm', 'setSeverityLevels', 'setServiceNames'],
            logsViewerConfigLogic({ id }),
            ['setSparklineBreakdownBy'],
        ],
        values: [
            logsViewerFiltersLogic({ id }),
            ['filters', 'utcDateRange'],
            logsViewerConfigLogic({ id }),
            ['sparklineBreakdownBy', 'orderBy'],
        ],
    })),

    actions({
        runQuery: (debounce?: integer) => ({ debounce }),
        fetchNextLogsPage: (limit?: number) => ({ limit }),
        truncateLogs: (limit: number) => ({ limit }),
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
        setLiveLogsCheckpoint: (liveLogsCheckpoint: string | null) => ({ liveLogsCheckpoint }),
        setHasMoreLogsToLoad: (hasMoreLogsToLoad: boolean) => ({ hasMoreLogsToLoad }),
        setLiveTailRunning: (enabled: boolean) => ({ enabled }),
        setLiveTailInterval: (interval: number) => ({ interval }),
        setLogs: (logs: LogMessage[]) => ({ logs }),
        setSparkline: (sparkline: any[]) => ({ sparkline }),
        setNextCursor: (nextCursor: string | null) => ({ nextCursor }),
        expireLiveTail: () => true,
        setLiveTailExpired: (liveTailExpired: boolean) => ({ liveTailExpired }),
        addLogsToSparkline: (logs: LogMessage[]) => logs,
        setInitialLogsLimit: (initialLogsLimit: number | null) => ({ initialLogsLimit }),
        pollForNewLogs: true,
        setMaxExportableLogs: (maxExportableLogs: number) => ({ maxExportableLogs }),
    }),

    reducers({
        initialLogsLimit: [
            DEFAULT_INITIAL_LOGS_LIMIT as number | null,
            {
                setInitialLogsLimit: (_, { initialLogsLimit }) => initialLogsLimit,
                fetchLogsSuccess: () => null,
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
        maxExportableLogs: [
            10_000 as number,
            {
                setMaxExportableLogs: (_, { maxExportableLogs }) => maxExportableLogs,
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
                            limit: values.initialLogsLimit ?? DEFAULT_LOGS_PAGE_SIZE,
                            orderBy: values.orderBy,
                            dateRange: values.utcDateRange,
                            searchTerm: values.filters.searchTerm,
                            filterGroup: values.filters.filterGroup as PropertyGroupFilter,
                            severityLevels: values.filters.severityLevels,
                            serviceNames: values.filters.serviceNames,
                        },
                        signal,
                    })
                    actions.setLogsAbortController(null)
                    actions.setHasMoreLogsToLoad(!!response.hasMore)
                    actions.setNextCursor(response.nextCursor ?? null)
                    actions.setMaxExportableLogs(response.maxExportableLogs)
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
                            limit: limit ?? DEFAULT_LOGS_PAGE_SIZE,
                            orderBy: values.orderBy,
                            dateRange: values.utcDateRange,
                            searchTerm: values.filters.searchTerm,
                            filterGroup: values.filters.filterGroup as PropertyGroupFilter,
                            severityLevels: values.filters.severityLevels,
                            serviceNames: values.filters.serviceNames,
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
                            searchTerm: values.filters.searchTerm,
                            filterGroup: values.filters.filterGroup as PropertyGroupFilter,
                            severityLevels: values.filters.severityLevels,
                            serviceNames: values.filters.serviceNames,
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
        liveTailDisabledReason: [
            (s) => [s.orderBy, s.filters, s.logsLoading, s.liveTailExpired],
            (
                orderBy: LogsQuery['orderBy'],
                filters: LogsViewerFilters,
                logsLoading: boolean,
                liveTailExpired: boolean
            ): string | undefined => {
                if (orderBy !== 'latest') {
                    return 'Live tail only works with "Latest" ordering'
                }

                if (filters.dateRange.date_to) {
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

    listeners(({ actions, values, cache }) => ({
        setSparklineBreakdownBy: () => {
            actions.fetchSparkline()
        },
        fetchLogsFailure: ({ error, errorObject }) => {
            if (isUserInitiatedError(error)) {
                return
            }
            lemonToast.error(`Failed to load logs: ${error}`)
            const { error_type, status_code } = classifyQueryError(errorObject ?? error)
            posthog.capture('logs query failed', {
                query_type: 'logs',
                error_type,
                status_code,
                error_message: String(error),
            })
        },
        fetchNextLogsPageFailure: ({ error, errorObject }) => {
            if (isUserInitiatedError(error)) {
                return
            }
            lemonToast.error(`Failed to load more logs: ${error}`)
            const { error_type, status_code } = classifyQueryError(errorObject ?? error)
            posthog.capture('logs query failed', {
                query_type: 'logs_next_page',
                error_type,
                status_code,
                error_message: String(error),
            })
        },
        fetchSparklineFailure: ({ error, errorObject }) => {
            if (isUserInitiatedError(error)) {
                return
            }
            const { error_type, status_code } = classifyQueryError(errorObject ?? error)
            posthog.capture('logs query failed', {
                query_type: 'sparkline',
                error_type,
                status_code,
                error_message: String(error),
            })
        },
        fetchLogsSuccess: ({ logs }) => {
            if (logs.length === 0) {
                posthog.capture('logs no results returned')
            } else {
                posthog.capture('logs results returned', { count: logs.length })
                globalSetupLogic.findMounted()?.actions.markTaskAsCompleted(SetupTaskId.ViewFirstLogs)
            }
        },
        fetchNextLogsPage: () => {
            posthog.capture('logs load more requested')
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
                    has_search_term: !!values.filters.searchTerm,
                    has_filters: values.filters.filterGroup.values.length > 0,
                    severity_count: values.filters.severityLevels?.length ?? 0,
                    service_count: values.filters.serviceNames?.length ?? 0,
                })
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
        expireLiveTail: async ({}, breakpoint) => {
            await breakpoint(30000)
            if (values.liveTailRunning) {
                return
            }
            actions.setLiveTailExpired(true)
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
                        limit: DEFAULT_LOGS_PAGE_SIZE,
                        orderBy: values.orderBy,
                        dateRange: values.utcDateRange,
                        searchTerm: values.filters.searchTerm,
                        filterGroup: values.filters.filterGroup as PropertyGroupFilter,
                        severityLevels: values.filters.severityLevels,
                        serviceNames: values.filters.serviceNames,
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
                            .slice(0, DEFAULT_LOGS_PAGE_SIZE)
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
                const { error_type, status_code } = classifyQueryError(error)
                posthog.capture('logs query failed', {
                    query_type: 'live_tail',
                    error_type,
                    status_code,
                    error_message: String(error),
                })
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

    afterMount(({ values, actions, props }) => {
        if (props.autoLoad && values.parsedLogs.length === 0) {
            actions.runQuery()
        }
    }),
])
