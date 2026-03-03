import equal from 'fast-deep-equal'
import { actions, afterMount, connect, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'
import posthog from 'posthog-js'

import api from 'lib/api'
import { Params } from 'scenes/sceneTypes'

import { HogQLQueryResponse, NodeKind } from '~/queries/schema/schema-general'
import { AnyPropertyFilter, FilterLogicalOperator, UniversalFiltersGroup } from '~/types'

import { issueFiltersLogic } from '../../../../components/IssueFilters/issueFiltersLogic'
import { syncSearchParams, updateSearchParams } from '../../../../utils'
import type { errorTrackingInsightsLogicType } from './errorTrackingInsightsLogicType'

export const INSIGHTS_LOGIC_KEY = 'insights'

const DEFAULT_DATE_RANGE = { date_from: '-7d', date_to: null }
const DEFAULT_FILTER_GROUP = {
    type: FilterLogicalOperator.And,
    values: [{ type: FilterLogicalOperator.And, values: [] }],
}
const DEFAULT_FILTER_TEST_ACCOUNTS = false

export interface InsightsSummaryStats {
    totalExceptions: number
    totalSessions: number
    crashSessions: number
    crashFreeRate: number
}

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
            ['dateRange', 'filterTestAccounts', 'filterGroup', 'mergedFilterGroup'],
        ],
        actions: [
            issueFiltersLogic({ logicKey: INSIGHTS_LOGIC_KEY }),
            ['setDateRange', 'setFilterGroup', 'setFilterTestAccounts'],
        ],
    })),

    actions({
        reload: true,
        incrementRefreshKey: true,
    }),

    reducers({
        refreshKey: [
            0 as number,
            {
                incrementRefreshKey: (state) => state + 1,
            },
        ],
    }),

    loaders(({ values }) => ({
        summaryStats: [
            null as InsightsSummaryStats | null,
            {
                loadSummaryStats: async () => {
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
                            properties: (values.mergedFilterGroup.values[0] as UniversalFiltersGroup)
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

    listeners(({ actions }) => ({
        setDateRange: () => {
            actions.loadSummaryStats()
        },
        setFilterTestAccounts: () => {
            actions.loadSummaryStats()
        },
        reload: () => {
            actions.incrementRefreshKey()
            actions.loadSummaryStats()
        },
    })),

    subscriptions(({ actions }) => ({
        mergedFilterGroup: () => {
            actions.loadSummaryStats()
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

    afterMount(() => {
        posthog.capture('error_tracking_insights_viewed')
    }),
])
