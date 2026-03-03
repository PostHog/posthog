import { actions, afterMount, connect, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'
import posthog from 'posthog-js'

import api from 'lib/api'

import { HogQLQueryResponse, NodeKind } from '~/queries/schema/schema-general'
import { AnyPropertyFilter, UniversalFiltersGroup } from '~/types'

import { issueFiltersLogic } from '../../../../components/IssueFilters/issueFiltersLogic'
import type { errorTrackingInsightsLogicType } from './errorTrackingInsightsLogicType'

export const INSIGHTS_LOGIC_KEY = 'insights'

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

    afterMount(() => {
        posthog.capture('error_tracking_insights_viewed')
    }),
])
