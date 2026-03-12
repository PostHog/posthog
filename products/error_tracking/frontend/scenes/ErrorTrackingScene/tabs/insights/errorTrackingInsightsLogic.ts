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

export interface SessionEndingError {
    issueId: string
    issueName: string
    sessionId: string
    exceptionTimestamp: string
    secondsUntilEnd: number
}

export interface TopUser {
    distinctId: string
    errorCount: number
    issueCount: number
}

export interface TopSession {
    sessionId: string
    distinctId: string
    errorCount: number
    issueCount: number
}

export interface PageError {
    url: string
    errorCount: number
    userCount: number
}

export interface BrowserError {
    browser: string
    errorCount: number
    sessionCount: number
    errorRate: number
}

export interface NewVsReturningRow {
    label: string
    errorCount: number
    userCount: number
    errorsPerUser: number
}

/** Convert a date string (relative like '-7d'/'-24h' or absolute ISO) to a HogQL expression */
function relativeDateToHogQL(dateStr: string): string {
    const relMatch = dateStr.match(/^-(\d+)([hdwm])$/)
    if (relMatch) {
        const [, num, unit] = relMatch
        const unitMap: Record<string, string> = { h: 'HOUR', d: 'DAY', w: 'WEEK', m: 'MONTH' }
        return `now() - INTERVAL ${num} ${unitMap[unit] ?? 'DAY'}`
    }
    // Absolute date - wrap in parseDateTimeBestEffortOrNull
    return `parseDateTimeBestEffortOrNull('${dateStr}')`
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

        sessionEndingErrors: [
            null as SessionEndingError[] | null,
            {
                loadSessionEndingErrors: async (_, breakpoint) => {
                    await breakpoint(10)
                    const response = await api.query({
                        kind: NodeKind.HogQLQuery,
                        query: `
                            SELECT
                                exc.properties.$exception_issue_id as issue_id,
                                any(coalesce(exc.properties.$exception_type, 'Unknown error')) as issue_name,
                                exc.$session_id as session_id,
                                max(exc.timestamp) as exception_ts,
                                dateDiff('millisecond', max(exc.timestamp), session_end) / 1000.0 as seconds_until_end
                            FROM events exc
                            INNER JOIN (
                                SELECT
                                    $session_id as sid,
                                    max(timestamp) as session_end
                                FROM events
                                WHERE {filters}
                                    AND notEmpty($session_id)
                                GROUP BY $session_id
                            ) sess ON exc.$session_id = sess.sid
                            WHERE {filters}
                                AND exc.event = '$exception'
                                AND notEmpty(exc.$session_id)
                                AND notEmpty(exc.properties.$exception_issue_id)
                            GROUP BY exc.properties.$exception_issue_id, exc.$session_id, sess.session_end
                            HAVING seconds_until_end <= 5 AND seconds_until_end >= 0
                            ORDER BY seconds_until_end ASC
                            LIMIT 10
                        `,
                        filters: getFilters(values),
                    })
                    const results = (response as HogQLQueryResponse)?.results ?? []
                    return results.map((row: any) => ({
                        issueId: row[0] as string,
                        issueName: row[1] as string,
                        sessionId: row[2] as string,
                        exceptionTimestamp: row[3] as string,
                        secondsUntilEnd: row[4] as number,
                    }))
                },
            },
        ],

        topUsersByErrors: [
            null as TopUser[] | null,
            {
                loadTopUsersByErrors: async (_, breakpoint) => {
                    await breakpoint(10)
                    const response = await api.query({
                        kind: NodeKind.HogQLQuery,
                        query: `
                            SELECT
                                distinct_id,
                                count() as error_count,
                                uniq(properties.$exception_issue_id) as issue_count
                            FROM events
                            WHERE {filters}
                                AND event = '$exception'
                            GROUP BY distinct_id
                            ORDER BY error_count DESC
                            LIMIT 10
                        `,
                        filters: getFilters(values),
                    })
                    const results = (response as HogQLQueryResponse)?.results ?? []
                    return results.map((row: any) => ({
                        distinctId: row[0] as string,
                        errorCount: row[1] as number,
                        issueCount: row[2] as number,
                    }))
                },
            },
        ],

        topSessionsByErrors: [
            null as TopSession[] | null,
            {
                loadTopSessionsByErrors: async (_, breakpoint) => {
                    await breakpoint(10)
                    const response = await api.query({
                        kind: NodeKind.HogQLQuery,
                        query: `
                            SELECT
                                $session_id as session_id,
                                any(distinct_id) as distinct_id,
                                count() as error_count,
                                uniq(properties.$exception_issue_id) as issue_count
                            FROM events
                            WHERE {filters}
                                AND event = '$exception'
                                AND notEmpty($session_id)
                            GROUP BY $session_id
                            ORDER BY error_count DESC
                            LIMIT 10
                        `,
                        filters: getFilters(values),
                    })
                    const results = (response as HogQLQueryResponse)?.results ?? []
                    return results.map((row: any) => ({
                        sessionId: row[0] as string,
                        distinctId: row[1] as string,
                        errorCount: row[2] as number,
                        issueCount: row[3] as number,
                    }))
                },
            },
        ],

        errorsByPage: [
            null as PageError[] | null,
            {
                loadErrorsByPage: async (_, breakpoint) => {
                    await breakpoint(10)
                    const response = await api.query({
                        kind: NodeKind.HogQLQuery,
                        query: `
                            SELECT
                                properties.$current_url as url,
                                count() as error_count,
                                uniq(distinct_id) as user_count
                            FROM events
                            WHERE {filters}
                                AND event = '$exception'
                                AND notEmpty(properties.$current_url)
                            GROUP BY url
                            ORDER BY error_count DESC
                            LIMIT 10
                        `,
                        filters: getFilters(values),
                    })
                    const results = (response as HogQLQueryResponse)?.results ?? []
                    return results.map((row: any) => ({
                        url: row[0] as string,
                        errorCount: row[1] as number,
                        userCount: row[2] as number,
                    }))
                },
            },
        ],

        errorsByBrowser: [
            null as BrowserError[] | null,
            {
                loadErrorsByBrowser: async (_, breakpoint) => {
                    await breakpoint(10)
                    const response = await api.query({
                        kind: NodeKind.HogQLQuery,
                        query: `
                            SELECT
                                properties.$browser as browser,
                                countIf(event = '$exception') as error_count,
                                uniqIf($session_id, notEmpty($session_id)) as session_count,
                                if(session_count > 0, round(error_count / session_count * 100, 1), 0) as error_rate
                            FROM events
                            WHERE {filters}
                                AND notEmpty(properties.$browser)
                            GROUP BY browser
                            HAVING error_count > 0
                            ORDER BY error_count DESC
                            LIMIT 10
                        `,
                        filters: getFilters(values),
                    })
                    const results = (response as HogQLQueryResponse)?.results ?? []
                    return results.map((row: any) => ({
                        browser: row[0] as string,
                        errorCount: row[1] as number,
                        sessionCount: row[2] as number,
                        errorRate: row[3] as number,
                    }))
                },
            },
        ],

        errorsNewVsReturning: [
            null as NewVsReturningRow[] | null,
            {
                loadErrorsNewVsReturning: async (_, breakpoint) => {
                    await breakpoint(10)
                    // Users whose first-ever event falls within the queried date range = "New"
                    // Users whose first-ever event is older = "Returning"
                    const dateFrom = values.dateRange.date_from ?? '-7d'
                    const dateExpr = relativeDateToHogQL(dateFrom)
                    const response = await api.query({
                        kind: NodeKind.HogQLQuery,
                        query: `
                            WITH error_users AS (
                                SELECT distinct_id, count() as error_count
                                FROM events
                                WHERE {filters} AND event = '$exception'
                                GROUP BY distinct_id
                            ),
                            user_first_seen AS (
                                SELECT distinct_id, min(timestamp) as first_seen
                                FROM events
                                WHERE distinct_id IN (SELECT distinct_id FROM error_users)
                                GROUP BY distinct_id
                            )
                            SELECT
                                if(ufs.first_seen >= ${dateExpr}, 'New users', 'Returning users') as label,
                                sum(eu.error_count) as error_count,
                                count() as user_count,
                                if(user_count > 0, round(error_count / user_count, 1), 0) as errors_per_user
                            FROM error_users eu
                            JOIN user_first_seen ufs ON eu.distinct_id = ufs.distinct_id
                            GROUP BY label
                            ORDER BY error_count DESC
                        `,
                        filters: getFilters(values),
                    })
                    const results = (response as HogQLQueryResponse)?.results ?? []
                    return results.map((row: any) => ({
                        label: row[0] as string,
                        errorCount: row[1] as number,
                        userCount: row[2] as number,
                        errorsPerUser: row[3] as number,
                    }))
                },
            },
        ],
    })),

    listeners(({ actions }) => ({
        loadAllCustomInsights: () => {
            actions.loadSummaryStats(null)
            actions.loadSessionEndingErrors(null)
            actions.loadTopUsersByErrors(null)
            actions.loadTopSessionsByErrors(null)
            actions.loadErrorsByPage(null)
            actions.loadErrorsByBrowser(null)
            actions.loadErrorsNewVsReturning(null)
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
