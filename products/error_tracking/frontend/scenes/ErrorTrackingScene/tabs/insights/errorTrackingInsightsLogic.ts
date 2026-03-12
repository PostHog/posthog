import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
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
    buildAffectedUsersRateQuery,
    buildCrashFreeSessionsQuery,
    buildErrorsByPageQuery,
    buildExceptionVolumeQuery,
    buildSessionEndingIssuesQuery,
    ErrorsByPageStrategy,
    InsightQueryFilters,
    SESSION_ENDING_EVENT_THRESHOLDS,
    SESSION_ENDING_TIME_THRESHOLDS,
    SessionEndingStrategy,
    SUMMARY_STATS_QUERY,
} from './queries'

export interface InsightsSummaryStats {
    totalExceptions: number
    affectedUsers: number
    totalSessions: number
    crashSessions: number
    crashFreeRate: number
}

export interface SessionEndingIssue {
    issueId: string
    issueName: string
    issueDescription: string
    endedSessions: number
    exampleRecordingSessionId: string | null
}

export interface PageErrorRate {
    url: string
    denominator: number
    errors: number
    errorRate: number
}

function getFilters(values: {
    dateRange: { date_from?: string | null; date_to?: string | null }
    filterTestAccounts: boolean
    insightsFilterGroup: UniversalFiltersGroup
}): { dateRange: typeof values.dateRange; filterTestAccounts: boolean; properties: AnyPropertyFilter[] } {
    return {
        dateRange: values.dateRange,
        filterTestAccounts: values.filterTestAccounts,
        properties: (values.insightsFilterGroup.values[0] as UniversalFiltersGroup).values as AnyPropertyFilter[],
    }
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

    actions({
        loadAllCustomInsights: true,
        setSessionEndingStrategy: (strategy: SessionEndingStrategy) => ({ strategy }),
        setSessionEndingTimeThreshold: (threshold: number) => ({ threshold }),
        setSessionEndingEventThreshold: (threshold: number) => ({ threshold }),
        setErrorsByPageStrategy: (strategy: ErrorsByPageStrategy) => ({ strategy }),
    }),

    reducers({
        sessionEndingStrategy: [
            'time' as SessionEndingStrategy,
            { setSessionEndingStrategy: (_, { strategy }) => strategy },
        ],
        sessionEndingTimeThreshold: [
            SESSION_ENDING_TIME_THRESHOLDS[1], // 5s default
            { setSessionEndingTimeThreshold: (_, { threshold }) => threshold },
        ],
        sessionEndingEventThreshold: [
            SESSION_ENDING_EVENT_THRESHOLDS[1], // 2 events default
            { setSessionEndingEventThreshold: (_, { threshold }) => threshold },
        ],
        errorsByPageStrategy: [
            'visits' as ErrorsByPageStrategy,
            { setErrorsByPageStrategy: (_, { strategy }) => strategy },
        ],
    }),

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
        affectedUsersRateQuery: [
            (s) => [s.dateRange, s.insightQueryFilters],
            (dateRange, filters): InsightVizNode<TrendsQuery> =>
                buildAffectedUsersRateQuery(dateRange.date_from ?? '-7d', dateRange.date_to ?? null, filters),
        ],
        crashFreeSessionsQuery: [
            (s) => [s.dateRange, s.insightQueryFilters],
            (dateRange, filters): InsightVizNode<TrendsQuery> =>
                buildCrashFreeSessionsQuery(dateRange.date_from ?? '-7d', dateRange.date_to ?? null, filters),
        ],
        errorsByLocationQuery: [
            (s) => [s.dateRange, s.insightQueryFilters],
            (dateRange, filters): InsightVizNode<TrendsQuery> =>
                buildErrorsByLocationQuery(dateRange.date_from ?? '-7d', dateRange.date_to ?? null, filters),
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
                        query: SUMMARY_STATS_QUERY,
                        filters: getFilters(values),
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

        sessionEndingIssues: [
            null as SessionEndingIssue[] | null,
            {
                loadSessionEndingIssues: async (_, breakpoint) => {
                    await breakpoint(10)
                    const threshold =
                        values.sessionEndingStrategy === 'time'
                            ? values.sessionEndingTimeThreshold
                            : values.sessionEndingEventThreshold
                    const response = await api.query({
                        kind: NodeKind.HogQLQuery,
                        query: buildSessionEndingIssuesQuery(values.sessionEndingStrategy, threshold),
                        filters: getFilters(values),
                    })
                    const results = (response as HogQLQueryResponse)?.results ?? []
                    return results.map((row: any) => ({
                        issueId: row[0] as string,
                        issueName: row[1] as string,
                        issueDescription: row[2] as string,
                        endedSessions: row[3] as number,
                        exampleRecordingSessionId: (row[4] as string) || null,
                    }))
                },
            },
        ],

        errorsByPage: [
            null as PageErrorRate[] | null,
            {
                loadErrorsByPage: async (_, breakpoint) => {
                    await breakpoint(10)
                    const response = await api.query({
                        kind: NodeKind.HogQLQuery,
                        query: buildErrorsByPageQuery(values.errorsByPageStrategy),
                        filters: getFilters(values),
                    })
                    const results = (response as HogQLQueryResponse)?.results ?? []
                    return results.map((row: any) => ({
                        url: row[0] as string,
                        denominator: row[1] as number,
                        errors: row[2] as number,
                        errorRate: row[3] as number,
                    }))
                },
            },
        ],
    })),

    listeners(({ actions }) => ({
        loadAllCustomInsights: () => {
            actions.loadSummaryStats(null)
            actions.loadSessionEndingIssues(null)
            actions.loadErrorsByPage(null)
        },
        setDateRange: () => actions.loadAllCustomInsights(),
        setFilterTestAccounts: () => actions.loadAllCustomInsights(),
        setSessionEndingStrategy: () => actions.loadSessionEndingIssues(null),
        setSessionEndingTimeThreshold: () => actions.loadSessionEndingIssues(null),
        setSessionEndingEventThreshold: () => actions.loadSessionEndingIssues(null),
        setErrorsByPageStrategy: () => actions.loadErrorsByPage(null),
    })),

    subscriptions(({ actions }) => ({
        insightsFilterGroup: () => {
            actions.loadAllCustomInsights()
        },
    })),

    afterMount(({ actions }) => {
        posthog.capture('error_tracking_insights_viewed')
        actions.loadAllCustomInsights()
    }),
])
