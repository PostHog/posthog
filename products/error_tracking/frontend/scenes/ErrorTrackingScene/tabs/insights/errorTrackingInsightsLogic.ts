import { afterMount, connect, kea, listeners, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'
import posthog from 'posthog-js'

import api from 'lib/api'

import { HogQLQueryResponse, InsightVizNode, NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { AnyPropertyFilter, FilterLogicalOperator, PropertyFilterType, UniversalFiltersGroup } from '~/types'

import { issueFiltersLogic } from '../../../../components/IssueFilters/issueFiltersLogic'
import { ERROR_TRACKING_SCENE_LOGIC_KEY } from '../../errorTrackingSceneLogic'
import type { errorTrackingInsightsLogicType } from './errorTrackingInsightsLogicType'
import {
    buildAffectedUsersQuery,
    buildCrashFreeSessionsQuery,
    buildExceptionVolumeQuery,
    InsightQueryFilters,
} from './queries'

export interface InsightsSummaryStats {
    totalExceptions: number
    affectedUsers: number
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
            issueFiltersLogic({ logicKey: ERROR_TRACKING_SCENE_LOGIC_KEY }),
            ['dateRange', 'filterTestAccounts', 'filterGroup', 'mergedFilterGroup'],
        ],
        actions: [
            issueFiltersLogic({ logicKey: ERROR_TRACKING_SCENE_LOGIC_KEY }),
            ['setDateRange', 'setFilterGroup', 'setFilterTestAccounts'],
        ],
    })),

    selectors({
        insightsFilterGroup: [
            (s) => [s.mergedFilterGroup],
            (mergedFilterGroup): UniversalFiltersGroup => {
                const inner = mergedFilterGroup.values[0] as UniversalFiltersGroup
                return {
                    type: FilterLogicalOperator.And,
                    values: [
                        {
                            ...inner,
                            values: inner.values.filter((f: any) => f.type !== PropertyFilterType.ErrorTrackingIssue),
                        },
                    ],
                } as UniversalFiltersGroup
            },
        ],
        insightQueryFilters: [
            (s) => [s.insightsFilterGroup, s.filterTestAccounts],
            (insightsFilterGroup, filterTestAccounts): InsightQueryFilters => ({
                filterGroup: insightsFilterGroup,
                filterTestAccounts,
            }),
        ],
        exceptionVolumeQuery: [
            (s) => [s.dateRange, s.insightQueryFilters],
            (dateRange, filters): InsightVizNode<TrendsQuery> =>
                buildExceptionVolumeQuery(dateRange.date_from ?? '-7d', dateRange.date_to ?? null, filters),
        ],
        affectedUsersQuery: [
            (s) => [s.dateRange, s.insightQueryFilters],
            (dateRange, filters): InsightVizNode<TrendsQuery> =>
                buildAffectedUsersQuery(dateRange.date_from ?? '-7d', dateRange.date_to ?? null, filters),
        ],
        crashFreeSessionsQuery: [
            (s) => [s.dateRange, s.insightQueryFilters],
            (dateRange, filters): InsightVizNode<TrendsQuery> =>
                buildCrashFreeSessionsQuery(dateRange.date_from ?? '-7d', dateRange.date_to ?? null, filters),
        ],
    }),

    loaders(({ values }) => ({
        summaryStats: [
            null as InsightsSummaryStats | null,
            {
                loadSummaryStats: async (_, breakpoint) => {
                    await breakpoint(10)
                    const response = await api.query({
                        kind: NodeKind.HogQLQuery,
                        query: `
                            SELECT
                                countIf(event = '$exception') as total_exceptions,
                                uniqIf(person_id, event = '$exception') as affected_users,
                                uniqIf($session_id, notEmpty($session_id)) as total_sessions,
                                uniqIf($session_id, event = '$exception' AND notEmpty($session_id)) as crash_sessions
                            FROM events
                            WHERE {filters}
                        `,
                        filters: {
                            dateRange: values.dateRange,
                            filterTestAccounts: values.filterTestAccounts,
                            properties: (values.insightsFilterGroup.values[0] as UniversalFiltersGroup)
                                .values as AnyPropertyFilter[],
                        },
                    })
                    const row = (response as HogQLQueryResponse)?.results?.[0]
                    if (!row) {
                        return null
                    }
                    const [totalExceptions, affectedUsers, totalSessions, crashSessions] = row as [
                        number,
                        number,
                        number,
                        number,
                    ]
                    const crashFreeRate =
                        totalSessions > 0 ? ((totalSessions - crashSessions) / totalSessions) * 100 : 100

                    return {
                        totalExceptions,
                        affectedUsers,
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
            actions.loadSummaryStats(null)
        },
        setFilterTestAccounts: () => {
            actions.loadSummaryStats(null)
        },
    })),

    subscriptions(({ actions }) => ({
        insightsFilterGroup: () => {
            actions.loadSummaryStats(null)
        },
    })),

    afterMount(({ actions }) => {
        posthog.capture('error_tracking_insights_viewed')
        actions.loadSummaryStats(null)
    }),
])
