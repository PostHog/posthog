import { afterMount, connect, kea, listeners, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'
import posthog from 'posthog-js'

import api from 'lib/api'
import { isUniversalGroupFilterLike } from 'lib/components/UniversalFilters/utils'

import {
    DateRange,
    HogQLQueryResponse,
    InsightVizNode,
    NodeKind,
    ProductKey,
    TrendsQuery,
} from '~/queries/schema/schema-general'
import {
    AnyPropertyFilter,
    FilterLogicalOperator,
    PropertyFilterType,
    UniversalFiltersGroup,
    UniversalFiltersGroupValue,
} from '~/types'

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

function stripIssueFiltersFromGroup(group: UniversalFiltersGroup): UniversalFiltersGroup {
    const values = group.values.reduce<UniversalFiltersGroupValue[]>((strippedValues, filter) => {
        if (isUniversalGroupFilterLike(filter)) {
            const strippedGroup = stripIssueFiltersFromGroup(filter)
            if (strippedGroup.values.length > 0) {
                strippedValues.push(strippedGroup)
            }
            return strippedValues
        }

        if (filter.type !== PropertyFilterType.ErrorTrackingIssue) {
            strippedValues.push(filter)
        }
        return strippedValues
    }, [])

    return { ...group, values }
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
                    values: [stripIssueFiltersFromGroup(inner)],
                } as UniversalFiltersGroup
            },
        ],
        // Flat property list shared by the HogQL summary query and the embedded TrendsQuery charts.
        // Both paths must use the same shape — passing a wrapped group to one path and a flat list
        // to the other can cause the summary stats and charts to disagree on which events match.
        effectiveProperties: [
            (s) => [s.insightsFilterGroup],
            (insightsFilterGroup): AnyPropertyFilter[] => {
                const inner = insightsFilterGroup.values[0] as UniversalFiltersGroup | undefined
                return (inner?.values ?? []) as AnyPropertyFilter[]
            },
        ],
        // Single source of truth for the date range used by both the summary stats query and the charts.
        effectiveDateRange: [
            (s) => [s.dateRange],
            (dateRange): DateRange => ({
                date_from: dateRange.date_from ?? '-7d',
                date_to: dateRange.date_to ?? null,
            }),
        ],
        insightQueryFilters: [
            (s) => [s.effectiveProperties, s.filterTestAccounts],
            (properties, filterTestAccounts): InsightQueryFilters => ({
                properties,
                filterTestAccounts,
            }),
        ],
        exceptionVolumeQuery: [
            (s) => [s.effectiveDateRange, s.insightQueryFilters],
            (dateRange, filters): InsightVizNode<TrendsQuery> => buildExceptionVolumeQuery(dateRange, filters),
        ],
        affectedUsersQuery: [
            (s) => [s.effectiveDateRange, s.insightQueryFilters],
            (dateRange, filters): InsightVizNode<TrendsQuery> => buildAffectedUsersQuery(dateRange, filters),
        ],
        crashFreeSessionsQuery: [
            (s) => [s.effectiveDateRange, s.insightQueryFilters],
            (dateRange, filters): InsightVizNode<TrendsQuery> => buildCrashFreeSessionsQuery(dateRange, filters),
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
                            dateRange: values.effectiveDateRange,
                            filterTestAccounts: values.filterTestAccounts,
                            properties: values.effectiveProperties,
                        },
                        tags: { productKey: ProductKey.ERROR_TRACKING },
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
