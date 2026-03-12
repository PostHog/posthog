import { actions, afterMount, connect, kea, listeners, path, selectors } from 'kea'
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
    buildErrorsByLocationQuery,
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

export interface SessionEndingIssue {
    issueId: string
    issueName: string
    issueDescription: string
    endedSessions: number
}

export interface PageErrorRate {
    url: string
    pageviews: number
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
                        query: `
                            SELECT
                                countIf(event = '$exception') as total_exceptions,
                                uniqIf(person_id, event = '$exception') as affected_users,
                                uniqIf($session_id, notEmpty($session_id)) as total_sessions,
                                uniqIf($session_id, event = '$exception' AND notEmpty($session_id)) as crash_sessions
                            FROM events
                            WHERE {filters}
                        `,
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
                    // Group by issue_id: count how many distinct sessions ended
                    // within 5s of that issue's exception
                    const response = await api.query({
                        kind: NodeKind.HogQLQuery,
                        query: `
                            WITH session_ends AS (
                                SELECT
                                    $session_id as sid,
                                    max(timestamp) as session_end
                                FROM events
                                WHERE {filters}
                                    AND notEmpty($session_id)
                                GROUP BY $session_id
                            ),
                            top_issues AS (
                                SELECT
                                    issue_id,
                                    uniq(exc.$session_id) as ended_sessions
                                FROM events exc
                                INNER JOIN session_ends se ON exc.$session_id = se.sid
                                WHERE {filters}
                                    AND exc.event = '$exception'
                                    AND notEmpty(exc.$session_id)
                                    AND notEmpty(exc.properties.$exception_issue_id)
                                    AND dateDiff('second', exc.timestamp, se.session_end) <= 5
                                GROUP BY issue_id
                                ORDER BY ended_sessions DESC
                                LIMIT 10
                            )
                            SELECT
                                ti.issue_id,
                                eti.name as issue_name,
                                eti.description as issue_description,
                                ti.ended_sessions
                            FROM top_issues ti
                            LEFT JOIN (
                                SELECT id, name, description FROM system.error_tracking_issues
                                WHERE id IN (SELECT issue_id FROM top_issues)
                            ) AS eti ON eti.id = ti.issue_id
                            ORDER BY ended_sessions DESC
                        `,
                        filters: getFilters(values),
                    })
                    const results = (response as HogQLQueryResponse)?.results ?? []
                    return results.map((row: any) => ({
                        issueId: row[0] as string,
                        issueName: row[1] as string,
                        issueDescription: row[2] as string,
                        endedSessions: row[3] as number,
                    }))
                },
            },
        ],

        errorsByPage: [
            null as PageErrorRate[] | null,
            {
                loadErrorsByPage: async (_, breakpoint) => {
                    await breakpoint(10)
                    // For each URL: count pageviews and exceptions, compute error rate
                    const response = await api.query({
                        kind: NodeKind.HogQLQuery,
                        query: `
                            SELECT
                                properties.$current_url as url,
                                countIf(event = '$pageview') as pageviews,
                                countIf(event = '$exception') as errors,
                                if(pageviews > 0, round(errors / pageviews * 100, 1), 0) as error_rate
                            FROM events
                            WHERE {filters}
                                AND event IN ('$pageview', '$exception')
                                AND notEmpty(properties.$current_url)
                            GROUP BY url
                            HAVING errors > 0 AND pageviews > 0
                            ORDER BY error_rate DESC
                            LIMIT 10
                        `,
                        filters: getFilters(values),
                    })
                    const results = (response as HogQLQueryResponse)?.results ?? []
                    return results.map((row: any) => ({
                        url: row[0] as string,
                        pageviews: row[1] as number,
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
        setDateRange: () => {
            actions.loadAllCustomInsights()
        },
        setFilterTestAccounts: () => {
            actions.loadAllCustomInsights()
        },
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
