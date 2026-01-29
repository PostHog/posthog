import { actions, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { SetupTaskId, globalSetupLogic } from 'lib/components/ProductSetup'

import { LogMessage, LogsQuery } from '~/queries/schema/schema-general'
import { PropertyGroupFilter } from '~/types'

import type { logsViewerDataLogicType } from './logsViewerDataLogicType'

const NEW_QUERY_STARTED_ERROR_MESSAGE = 'new query started' as const

export interface LogsViewerDataLogicProps {
    id: string
}

export type FetchLogsPayload = Omit<LogsQuery, 'kind'>

export const logsViewerDataLogic = kea<logsViewerDataLogicType>([
    path(['products', 'logs', 'frontend', 'components', 'LogsViewer', 'data', 'logsViewerDataLogic']),
    props({ id: 'default' } as LogsViewerDataLogicProps),
    key((props) => props.id),

    actions({
        fetchLogs: (payload: FetchLogsPayload) => ({ payload }),
        fetchNextPage: true,
        clearLogs: true,
        truncateLogs: (limit: number) => ({ limit }),
        setLogs: (logs: LogMessage[]) => ({ logs }),
        setLogsAbortController: (logsAbortController: AbortController | null) => ({ logsAbortController }),
        setHasMoreLogsToLoad: (hasMoreLogsToLoad: boolean) => ({ hasMoreLogsToLoad }),
        setNextCursor: (nextCursor: string | null) => ({ nextCursor }),
        cancelInProgressFetchLogs: (logsAbortController: AbortController | null, reason: string) => ({
            logsAbortController,
            reason,
        }),
    }),

    reducers({
        logs: [
            [] as LogMessage[],
            {
                fetchLogsSuccess: (_, { logsResponse }) => logsResponse,
                fetchNextPageSuccess: (state, { logsResponse }) => [...state, ...logsResponse],
                clearLogs: () => [],
                truncateLogs: (state, { limit }) => state.slice(0, limit),
                setLogs: (_, { logs }) => logs,
            },
        ],
        lastFetchPayload: [
            null as FetchLogsPayload | null,
            {
                fetchLogs: (_, { payload }) => payload,
            },
        ],
        logsAbortController: [
            null as AbortController | null,
            {
                setLogsAbortController: (_, { logsAbortController }) => logsAbortController,
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
    }),

    loaders(({ actions, values }) => {
        const _fetchLogs = async (
            payload: FetchLogsPayload,
            breakpoint: (ms: number) => Promise<void>,
            debounceMs: number = 0
        ): Promise<LogMessage[]> => {
            if (debounceMs > 0) {
                await breakpoint(debounceMs)
            }

            const logsController = new AbortController()
            const signal = logsController.signal
            actions.cancelInProgressFetchLogs(logsController, NEW_QUERY_STARTED_ERROR_MESSAGE)

            const response = await api.logs.query({
                query: {
                    limit: payload.limit,
                    orderBy: payload.orderBy,
                    dateRange: payload.dateRange,
                    searchTerm: payload.searchTerm,
                    filterGroup: payload.filterGroup as PropertyGroupFilter,
                    severityLevels: payload.severityLevels,
                    serviceNames: payload.serviceNames,
                    after: payload.after,
                },
                signal,
            })

            if (values.logsAbortController === logsController) {
                actions.setLogsAbortController(null)
            }
            actions.setHasMoreLogsToLoad(!!response.hasMore)
            actions.setNextCursor(response.nextCursor ?? null)
            return response.results
        }

        return {
            logsResponse: {
                __default: [] as LogMessage[],
                fetchLogs: async ({ payload }: { payload: FetchLogsPayload }, breakpoint) => {
                    return await _fetchLogs(payload, breakpoint)
                },
                fetchNextPage: async (_, breakpoint) => {
                    if (!values.lastFetchPayload || !values.nextCursor) {
                        return []
                    }
                    posthog.capture('logs load more requested', { query: values.lastFetchPayload })
                    return await _fetchLogs({ ...values.lastFetchPayload, after: values.nextCursor }, breakpoint, 300)
                },
            },
        }
    }),

    selectors({
        logsLoading: [(s) => [s.logsResponseLoading], (logsResponseLoading: boolean) => logsResponseLoading],
    }),

    listeners(({ actions, values }) => ({
        fetchLogsSuccess: ({ logsResponse, payload }) => {
            const query = payload?.payload
            if (logsResponse.length === 0) {
                posthog.capture('logs no results returned', { query })
            } else {
                posthog.capture('logs results returned', { count: logsResponse.length, query })
                globalSetupLogic.findMounted()?.actions.markTaskAsCompleted(SetupTaskId.ViewFirstLogs)
            }
        },
        fetchLogsFailure: ({ error }) => {
            const errorStr = String(error).toLowerCase()
            if (error !== NEW_QUERY_STARTED_ERROR_MESSAGE && !errorStr.includes('abort')) {
                lemonToast.error(`Failed to load logs: ${error}`)
                posthog.captureException(error)
            }
        },
        fetchNextPageFailure: ({ error }) => {
            const errorStr = String(error).toLowerCase()
            if (error !== NEW_QUERY_STARTED_ERROR_MESSAGE && !errorStr.includes('abort')) {
                lemonToast.error(`Failed to load more logs: ${error}`)
                posthog.captureException(error)
            }
        },
        cancelInProgressFetchLogs: ({ logsAbortController, reason }) => {
            if (values.logsAbortController !== null) {
                values.logsAbortController.abort(reason)
            }
            actions.setLogsAbortController(logsAbortController)
        },
    })),

    events(({ actions }) => ({
        beforeUnmount: () => {
            actions.cancelInProgressFetchLogs(null, 'unmounting component')
        },
    })),
])
