import equal from 'fast-deep-equal'
import { actions, afterMount, connect, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'
import posthog from 'posthog-js'

import api from 'lib/api'
import { Params } from 'scenes/sceneTypes'

import { HogQLQueryResponse, NodeKind } from '~/queries/schema/schema-general'
import { AnyPropertyFilter, FilterLogicalOperator, UniversalFiltersGroup } from '~/types'

import { issueFiltersLogic } from '../../../../components/IssueFilters/issueFiltersLogic'
import { syncSearchParams, updateSearchParams } from '../../../../utils'
import type { errorTrackingInsightsLogicType } from './errorTrackingInsightsLogicType'

export const INSIGHTS_LOGIC_KEY = 'insights'

export type InsightsTrackableItem = 'summary_stats' | 'exception_volume' | 'crash_free_sessions'

const TRACKABLE_ITEMS: InsightsTrackableItem[] = ['summary_stats', 'exception_volume', 'crash_free_sessions']

export interface InsightsSummaryStats {
    totalExceptions: number
    totalSessions: number
    crashSessions: number
    crashFreeRate: number
}

const DEFAULT_DATE_RANGE = { date_from: '-7d', date_to: null }
const DEFAULT_FILTER_GROUP = {
    type: FilterLogicalOperator.And,
    values: [{ type: FilterLogicalOperator.And, values: [] }],
}
const DEFAULT_FILTER_TEST_ACCOUNTS = false

export const errorTrackingInsightsLogic = kea<errorTrackingInsightsLogicType>([
    path([
        'products',
        'error_tracking',
        'scenes',
        'ErrorTrackingScene',
        'tabs',
        'insights',
        'errorTrackingInsightsLogic',
    ]),

    connect(() => ({
        values: [
            issueFiltersLogic({ logicKey: INSIGHTS_LOGIC_KEY }),
            ['dateRange', 'filterTestAccounts', 'filterGroup'],
        ],
        actions: [
            issueFiltersLogic({ logicKey: INSIGHTS_LOGIC_KEY }),
            ['setDateRange', 'setFilterGroup', 'setFilterTestAccounts'],
        ],
    })),

    actions({
        reload: true,
        setLoadStartTime: (time: number) => ({ time }),
        reportItemLoaded: (item: InsightsTrackableItem, durationMs: number) => ({ item, durationMs }),
        incrementRefreshKey: true,
    }),

    reducers({
        loadStartTime: [
            0 as number,
            {
                setLoadStartTime: (_, { time }) => time,
            },
        ],
        itemTimings: [
            {} as Partial<Record<InsightsTrackableItem, number>>,
            {
                setLoadStartTime: () => ({}),
                reportItemLoaded: (state, { item, durationMs }) => ({ ...state, [item]: durationMs }),
            },
        ],
        refreshKey: [
            0 as number,
            {
                incrementRefreshKey: (state) => state + 1,
            },
        ],
    }),

    loaders(({ actions, values }) => ({
        summaryStats: [
            null as InsightsSummaryStats | null,
            {
                loadSummaryStats: async () => {
                    const startTime = performance.now()
                    const response = await api.query({
                        kind: NodeKind.HogQLQuery,
                        query: `
                            SELECT
                                countIf(event = '$exception') as total_exceptions,
                                uniqIf($session_id, notEmpty($session_id)) as total_sessions,
                                uniqIf($session_id, event = '$exception' AND notEmpty($session_id)) as crash_sessions
                            FROM events
                            WHERE {filters}
                        `,
                        filters: {
                            dateRange: values.dateRange,
                            filterTestAccounts: values.filterTestAccounts,
                            properties: (values.filterGroup.values[0] as UniversalFiltersGroup)
                                .values as AnyPropertyFilter[],
                        },
                    })
                    const row = (response as HogQLQueryResponse)?.results?.[0]
                    if (!row) {
                        return null
                    }
                    const [totalExceptions, totalSessions, crashSessions] = row as [number, number, number]
                    const crashFreeRate =
                        totalSessions > 0 ? ((totalSessions - crashSessions) / totalSessions) * 100 : 100

                    actions.reportItemLoaded('summary_stats', Math.round(performance.now() - startTime))

                    return {
                        totalExceptions,
                        totalSessions,
                        crashSessions,
                        crashFreeRate: Math.round(crashFreeRate * 100) / 100,
                    }
                },
            },
        ],
    })),

    listeners(({ actions, values }) => ({
        setDateRange: () => {
            actions.setLoadStartTime(performance.now())
            actions.loadSummaryStats()
        },
        setFilterTestAccounts: () => {
            actions.setLoadStartTime(performance.now())
            actions.loadSummaryStats()
        },
        setFilterGroup: () => {
            actions.setLoadStartTime(performance.now())
            actions.loadSummaryStats()
        },
        reload: () => {
            actions.setLoadStartTime(performance.now())
            actions.incrementRefreshKey()
            actions.loadSummaryStats()
        },
        reportItemLoaded: ({ item, durationMs }) => {
            const updatedTimings = { ...values.itemTimings, [item]: durationMs }
            const allLoaded = TRACKABLE_ITEMS.every((key) => updatedTimings[key] !== undefined)
            if (allLoaded) {
                posthog.capture('error_tracking_insights_data_loaded', {
                    date_from: values.dateRange.date_from,
                    date_to: values.dateRange.date_to,
                    duration_ms_summary_stats: updatedTimings.summary_stats,
                    duration_ms_exception_volume: updatedTimings.exception_volume,
                    duration_ms_crash_free_sessions: updatedTimings.crash_free_sessions,
                })
            }
        },
    })),

    urlToAction(({ actions, values }) => ({
        '**/error_tracking': (_, params: Params) => {
            const dateRange = params.insights_dateRange ?? DEFAULT_DATE_RANGE
            if (!equal(dateRange, values.dateRange)) {
                actions.setDateRange(dateRange)
            }
            const filterGroup = params.insights_filterGroup ?? DEFAULT_FILTER_GROUP
            if (!equal(filterGroup, values.filterGroup)) {
                actions.setFilterGroup(filterGroup)
            }
            const filterTestAccounts = params.insights_filterTestAccounts ?? DEFAULT_FILTER_TEST_ACCOUNTS
            if (!equal(filterTestAccounts, values.filterTestAccounts)) {
                actions.setFilterTestAccounts(filterTestAccounts)
            }
        },
    })),

    actionToUrl(({ values }) => {
        const buildURL = (): ReturnType<typeof syncSearchParams> =>
            syncSearchParams(router, (params: Params) => {
                updateSearchParams(params, 'insights_dateRange', values.dateRange, DEFAULT_DATE_RANGE)
                updateSearchParams(params, 'insights_filterGroup', values.filterGroup, DEFAULT_FILTER_GROUP)
                updateSearchParams(
                    params,
                    'insights_filterTestAccounts',
                    values.filterTestAccounts,
                    DEFAULT_FILTER_TEST_ACCOUNTS
                )
                return params
            })

        return {
            setDateRange: buildURL,
            setFilterGroup: buildURL,
            setFilterTestAccounts: buildURL,
        }
    }),

    afterMount(({ actions }) => {
        posthog.capture('error_tracking_insights_viewed')
        actions.loadSummaryStats()
    }),
])
