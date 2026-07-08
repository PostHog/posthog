import colors from 'ansi-colors'
import equal from 'fast-deep-equal'
import { actions, afterMount, connect, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { dataColorVars } from 'lib/colors'
import { SetupTaskId, globalSetupLogic } from 'lib/components/ProductSetup'
import { dayjs } from 'lib/dayjs'
import { humanFriendlyDetailedTime } from 'lib/utils/datetime'
import { teamLogic } from 'scenes/teamLogic'

import {
    LogMessage,
    LogsQuery,
    LogsSparklineBreakdownBy,
    ProductIntentContext,
    ProductKey,
} from '~/queries/schema/schema-general'
import { integer } from '~/queries/schema/type-utils'
import { JsonType, PropertyGroupFilter, UniversalFiltersGroup, UniversalFiltersGroupValue } from '~/types'

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

// Parse cache keyed on log object identity — leak-free by construction (entries die with their
// logs) and shared across logic instances. Parsing is pure per object, so cached entries are
// always correct as long as log objects are never mutated in place after creation (they aren't:
// `logs` is only ever replaced wholesale via `setLogs`). The same immutability contract is why
// live-tail prepends can keep existing log references untouched so their parsed rows stay
// reference-stable, and why newLogUuids is tracked as a separate set rather than a flag on each
// log — avoiding a clone of every existing log object per poll tick.
const parsedLogCache = new WeakMap<LogMessage, ParsedLogMessage>()
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

/** Returns true if the filterGroup change should be skipped (no real change or new empty filter added). */
export function shouldSkipFilterGroupChange(
    filterGroup: UniversalFiltersGroup,
    oldFilterGroup: UniversalFiltersGroup | undefined
): boolean {
    if (!oldFilterGroup || equal(filterGroup, oldFilterGroup)) {
        return true
    }
    const oldCount = (oldFilterGroup.values?.[0] as UniversalFiltersGroup | undefined)?.values?.length ?? 0
    const newCount = (filterGroup.values?.[0] as UniversalFiltersGroup | undefined)?.values?.length ?? 0
    if (newCount <= oldCount) {
        return false
    }
    const hasIncompleteValue = (filterValue: UniversalFiltersGroupValue): boolean => {
        if (!filterValue || typeof filterValue !== 'object') {
            return false
        }
        if ('type' in filterValue && 'values' in filterValue) {
            const groupValues = (filterValue as UniversalFiltersGroup).values ?? []
            return groupValues.some((child) => hasIncompleteValue(child))
        }
        if ('id' in filterValue) {
            return (filterValue as { id: unknown }).id == null
        }
        if ('value' in filterValue) {
            const val = (filterValue as { value: unknown }).value
            return val == null || (Array.isArray(val) && val.length === 0)
        }
        return false
    }
    const rootGroup = filterGroup.values?.[0] as UniversalFiltersGroup | undefined
    const lastFilter = rootGroup?.values?.[rootGroup.values.length - 1]
    return lastFilter ? hasIncompleteValue(lastFilter) : false
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
            ['setSparklineBreakdownBy', 'setOrderBy', 'setColumns', 'addColumn', 'removeColumn'],
        ],
        values: [
            logsViewerFiltersLogic({ id }),
            ['filters', 'utcDateRange', 'filterGroup', 'queryFilterGroup'],
            logsViewerConfigLogic({ id }),
            ['sparklineBreakdownBy', 'orderBy', 'customColumns'],
        ],
    })),

    actions({
        handleQueryChange: (filterType: string, extraProps?: Record<string, unknown>) => ({
            filterType,
            extraProps,
        }),
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
        setNewLogUuids: (newLogUuids: string[]) => ({ newLogUuids }),
        setSparkline: (sparkline: any[] | null) => ({ sparkline }),
        setNextCursor: (nextCursor: string | null) => ({ nextCursor }),
        expireLiveTail: () => true,
        setLiveTailExpired: (liveTailExpired: boolean) => ({ liveTailExpired }),
        addLogsToSparkline: (logs: LogMessage[]) => logs,
        setInitialLogsLimit: (initialLogsLimit: number | null) => ({ initialLogsLimit }),
        pollForNewLogs: true,
        setMaxExportableLogs: (maxExportableLogs: number) => ({ maxExportableLogs }),
        // Aliases for the requested customColumns, echoed by the server in request order —
        // rows carry their custom values under these keys (see response `columns`)
        setCustomColumnAliases: (customColumnAliases: string[] | null) => ({ customColumnAliases }),
    }),

    reducers({
        // UUIDs of the last live-tail batch, for the one-shot row highlight (see parsedLogCache comment above).
        newLogUuids: [
            new Set<string>(),
            {
                setNewLogUuids: (_, { newLogUuids }) => new Set(newLogUuids),
                // A fresh query result set has no "just arrived" rows.
                fetchLogsSuccess: () => new Set<string>(),
                clearLogs: () => new Set<string>(),
            },
        ],
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
                // Drop the stale checkpoint when a new query starts so the still-loading region
                // can't flash against the previous query's data before the fresh one lands.
                clearLogs: () => null,
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
        customColumnAliases: [
            null as string[] | null,
            {
                setCustomColumnAliases: (_, { customColumnAliases }) => customColumnAliases,
                clearLogs: () => null,
            },
        ],
    }),

    loaders(({ values, actions, cache }) => ({
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
                            filterGroup: values.queryFilterGroup as PropertyGroupFilter,
                            severityLevels: values.filters.severityLevels,
                            serviceNames: values.filters.serviceNames,
                            customColumns: values.customColumns,
                        },
                        signal,
                    })
                    actions.setLogsAbortController(null)
                    actions.setHasMoreLogsToLoad(!!response.hasMore)
                    actions.setNextCursor(response.nextCursor ?? null)
                    actions.setMaxExportableLogs(response.maxExportableLogs)
                    actions.setCustomColumnAliases(response.columns ?? null)
                    cache.lastSentCustomColumns = JSON.stringify(values.customColumns ?? null)
                    // The checkpoint (fixed per query, identical on every row) marks the latest
                    // timestamp ingestion is known to have fully caught up to — used to flag the
                    // still-loading tail of the sparkline.
                    if (response.results.length > 0) {
                        actions.setLiveLogsCheckpoint(response.results[0].live_logs_checkpoint ?? null)
                    }
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
                            filterGroup: values.queryFilterGroup as PropertyGroupFilter,
                            severityLevels: values.filters.severityLevels,
                            serviceNames: values.filters.serviceNames,
                            customColumns: values.customColumns,
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
                            filterGroup: values.queryFilterGroup as PropertyGroupFilter,
                            severityLevels: values.filters.severityLevels,
                            serviceNames: values.filters.serviceNames,
                            sparklineBreakdownBy: values.sparklineBreakdownBy,
                        },
                        signal,
                    })
                    actions.setSparklineAbortController(null)
                    return response
                },
                setSparkline: ({ sparkline }) => sparkline ?? [],
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

                    // Existing log references are stable across polls — cache hit = no re-render.
                    const cached = parsedLogCache.get(log)
                    if (cached) {
                        result.push(cached)
                        continue
                    }

                    const cleanBody = colors.unstyle(log.body)
                    let parsedBody: JsonType | null = null
                    try {
                        parsedBody = JSON.parse(cleanBody)
                    } catch {
                        // Not JSON, that's fine
                    }
                    const parsed: ParsedLogMessage = {
                        ...log,
                        attributes: stringifyLogAttributes(log.attributes),
                        cleanBody,
                        parsedBody,
                        originalLog: log,
                    }
                    parsedLogCache.set(log, parsed)
                    result.push(parsed)
                }

                return result
            },
        ],
        sparklineData: [
            (s) => [s.sparkline, s.sparklineBreakdownBy],
            (sparkline: any[] | null, sparklineBreakdownBy: LogsSparklineBreakdownBy) => {
                if (!sparkline) {
                    return { labels: [], dates: [], data: [] }
                }

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

                return { data, labels, dates }
            },
        ],
        // Sparkline bar indices that are still being ingested (incomplete), to be hatched. A bucket is
        // incomplete when its end is past the ingestion checkpoint. The latest bucket is the in-progress
        // bar so the checkpoint always trails "now" a little; we only flag anything once the checkpoint
        // lags the latest bucket's *start* by at least a quarter of a bar, otherwise ingestion is
        // effectively caught up. When the lag spans more than two buckets but they're all empty, we flag
        // only the latest bar rather than hatching a wide empty stretch. Bucket times and the checkpoint
        // are both UTC ISO strings, so the relative comparison is timezone-safe.
        //
        // Empty while the sparkline query is in flight or before a fresh checkpoint lands (it's cleared
        // on each new query); otherwise the hatch flickers mid-load as new data and a new checkpoint race.
        sparklineIncompleteBarIndices: [
            (s) => [s.sparklineData, s.liveLogsCheckpoint, s.sparklineLoading],
            (
                sparklineData: { dates: string[]; data: { values: number[] }[] },
                liveLogsCheckpoint: string | null,
                sparklineLoading: boolean
            ): number[] => {
                const { dates, data } = sparklineData
                if (sparklineLoading || !liveLogsCheckpoint || dates.length < 2) {
                    return []
                }
                const firstBucketMs = dayjs(dates[0]).valueOf()
                const lastBucketMs = dayjs(dates[dates.length - 1]).valueOf()
                const intervalMs = dayjs(dates[1]).valueOf() - firstBucketMs
                if (intervalMs <= 0) {
                    return []
                }
                const checkpointMs = dayjs(liveLogsCheckpoint).valueOf()
                if (!Number.isFinite(checkpointMs) || lastBucketMs - checkpointMs < intervalMs * 0.25) {
                    return []
                }
                const incomplete = dates.reduce<number[]>((indices, date, index) => {
                    if (dayjs(date).valueOf() + intervalMs > checkpointMs) {
                        indices.push(index)
                    }
                    return indices
                }, [])
                const bucketTotal = (index: number): number =>
                    data.reduce((sum, series) => sum + (series.values[index] ?? 0), 0)
                if (incomplete.length > 2 && incomplete.every((index) => bucketTotal(index) === 0)) {
                    return [dates.length - 1]
                }
                return incomplete
            },
        ],
        totalLogsMatchingFilters: [
            (s) => [s.sparkline],
            (sparkline): number => sparkline?.reduce((sum: number, item: any) => sum + item.count, 0) ?? 0,
        ],
        logsRemainingToLoad: [
            (s) => [s.totalLogsMatchingFilters, s.logs],
            (totalLogsMatchingFilters, logs): number => totalLogsMatchingFilters - logs.length,
        ],
    }),

    subscriptions(({ actions }) => ({
        // Subscribe to the combined query view rather than the user-editable filterGroup
        // so the query reruns when pinned filters change (e.g. team `logs_distinct_id_attribute_key`
        // resolves after mount), not just when the user edits filters.
        queryFilterGroup: (filterGroup: UniversalFiltersGroup, oldFilterGroup: UniversalFiltersGroup | undefined) => {
            if (shouldSkipFilterGroupChange(filterGroup, oldFilterGroup)) {
                return
            }
            actions.handleQueryChange('attributes')
        },
    })),

    listeners(({ actions, values, cache }) => ({
        handleQueryChange: ({ filterType, extraProps }) => {
            if (values.hasRunQuery) {
                posthog.capture('logs filter changed', { filter_type: filterType, ...extraProps })
                actions.addProductIntent({
                    product_type: ProductKey.LOGS,
                    intent_context: ProductIntentContext.LOGS_SET_FILTERS,
                })
            }
            actions.runQuery()
        },
        setSearchTerm: ({ searchTerm }) => {
            actions.handleQueryChange('search', { search_term_length: searchTerm?.length ?? 0 })
        },
        setDateRange: () => {
            actions.handleQueryChange('date_range')
        },
        setSeverityLevels: ({ severityLevels }) => {
            actions.handleQueryChange('severity', { severity_levels: severityLevels ?? [] })
        },
        setServiceNames: ({ serviceNames }) => {
            actions.handleQueryChange('service', { service_count: serviceNames?.length ?? 0 })
        },
        setFilters: ({ pushToHistory }) => {
            if (pushToHistory) {
                actions.handleQueryChange('bulk')
            } else {
                actions.runQuery()
            }
        },
        setOrderBy: ({ orderBy, source }) => {
            posthog.capture('logs setting changed', { setting: 'order_by', value: orderBy, source })
            actions.runQuery()
        },
        setSparklineBreakdownBy: () => {
            actions.fetchSparkline()
        },
        // Structural column changes refetch only when the lowered wire value differs from what
        // the last query sent — resizing or reordering columns never re-runs the query.
        setColumns: () => {
            if (JSON.stringify(values.customColumns ?? null) !== cache.lastSentCustomColumns) {
                actions.runQuery()
            }
        },
        addColumn: () => {
            if (JSON.stringify(values.customColumns ?? null) !== cache.lastSentCustomColumns) {
                actions.runQuery()
            }
        },
        removeColumn: () => {
            if (JSON.stringify(values.customColumns ?? null) !== cache.lastSentCustomColumns) {
                actions.runQuery()
            }
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
            actions.clearLogs()
            actions.fetchLogs()
            actions.fetchSparkline()
            actions.cancelInProgressLiveTail(null)
        },
        cancelInProgressLogs: ({ logsAbortController }) => {
            if (values.logsAbortController !== null) {
                values.logsAbortController.abort(new DOMException(NEW_QUERY_STARTED_ERROR_MESSAGE, 'AbortError'))
            }
            actions.setLogsAbortController(logsAbortController)
        },
        cancelInProgressSparkline: ({ sparklineAbortController }) => {
            if (values.sparklineAbortController !== null) {
                values.sparklineAbortController.abort(new DOMException(NEW_QUERY_STARTED_ERROR_MESSAGE, 'AbortError'))
            }
            actions.setSparklineAbortController(sparklineAbortController)
        },
        cancelInProgressLiveTail: ({ liveTailAbortController }) => {
            if (values.liveTailAbortController !== null) {
                values.liveTailAbortController.abort(new DOMException('live tail request cancelled', 'AbortError'))
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
                        filterGroup: values.queryFilterGroup as PropertyGroupFilter,
                        severityLevels: values.filters.severityLevels,
                        serviceNames: values.filters.serviceNames,
                        customColumns: values.customColumns,
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
                    // Prepend new logs; existing references stay untouched (see parsedLogCache comment).
                    // Replacing newLogUuids highlights the new batch and un-highlights the previous one.
                    actions.setNewLogUuids(newLogs.map((log) => log.uuid))
                    actions.setLogs(
                        [...newLogs, ...values.logs]
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
                    // No new logs this tick — clear the previous batch's highlights so rows that
                    // scroll out and back don't replay the arrival animation on a quiet stream.
                    actions.setNewLogUuids([])
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
