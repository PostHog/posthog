import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { Dayjs, dayjs } from 'lib/dayjs'

import { NodeKind } from '~/queries/schema/schema-general'
import { FilterLogicalOperator, UniversalFiltersGroup } from '~/types'

import type { errorTrackingInsightsLogicType } from './errorTrackingInsightsLogicType'

export type InsightsViewMode = 'week' | 'month'

export interface InsightsSummaryStats {
    totalExceptions: number
    totalSessions: number
    crashSessions: number
    crashFreeRate: number
}

const DEFAULT_FILTER_GROUP: UniversalFiltersGroup = {
    type: FilterLogicalOperator.And,
    values: [{ type: FilterLogicalOperator.And, values: [] }],
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

    actions({
        setViewMode: (mode: InsightsViewMode) => ({ mode }),
        setAnchorDate: (date: Dayjs) => ({ date }),
        navigateBack: true,
        navigateForward: true,
        setFilterGroup: (filterGroup: UniversalFiltersGroup) => ({ filterGroup }),
        setFilterTestAccounts: (filterTestAccounts: boolean) => ({ filterTestAccounts }),
    }),

    reducers({
        viewMode: [
            'week' as InsightsViewMode,
            {
                setViewMode: (_, { mode }) => mode,
            },
        ],
        anchorDate: [
            dayjs().startOf('isoWeek') as Dayjs,
            {
                setAnchorDate: (_, { date }) => date,
            },
        ],
        filterGroup: [
            DEFAULT_FILTER_GROUP as UniversalFiltersGroup,
            {
                setFilterGroup: (_, { filterGroup }) =>
                    filterGroup?.values?.length ? filterGroup : DEFAULT_FILTER_GROUP,
            },
        ],
        filterTestAccounts: [
            false as boolean,
            {
                setFilterTestAccounts: (_, { filterTestAccounts }) => filterTestAccounts,
            },
        ],
    }),

    selectors({
        dateFrom: [(s) => [s.anchorDate], (anchorDate): string => anchorDate.format('YYYY-MM-DD')],
        dateTo: [
            (s) => [s.anchorDate, s.viewMode],
            (anchorDate, viewMode): string => {
                const end = viewMode === 'week' ? anchorDate.add(1, 'week') : anchorDate.add(1, 'month')
                const now = dayjs()
                const effective = end.isAfter(now) ? now : end
                return effective.format('YYYY-MM-DD')
            },
        ],
        chartDateTo: [
            (s) => [s.anchorDate, s.viewMode],
            (anchorDate, viewMode): string => {
                const end = viewMode === 'week' ? anchorDate.add(1, 'week') : anchorDate.add(1, 'month')
                return end.format('YYYY-MM-DD')
            },
        ],
        dateLabel: [
            (s) => [s.anchorDate, s.viewMode],
            (anchorDate, viewMode): string => {
                if (viewMode === 'week') {
                    const end = anchorDate.add(6, 'day')
                    return `${anchorDate.format('MMM D')} – ${end.format('MMM D, YYYY')}`
                }
                return anchorDate.format('MMMM YYYY')
            },
        ],
        relativeDateLabel: [
            (s) => [s.anchorDate, s.viewMode],
            (anchorDate, viewMode): string => {
                const now = dayjs()
                const unit = viewMode === 'week' ? 'week' : 'month'
                const currentPeriodStart = viewMode === 'week' ? now.startOf('isoWeek') : now.startOf('month')
                const diffPeriods = currentPeriodStart.diff(anchorDate, unit)
                if (diffPeriods === 0) {
                    return viewMode === 'week' ? 'this week' : 'this month'
                } else if (diffPeriods === 1) {
                    return viewMode === 'week' ? 'last week' : 'last month'
                }
                return `${diffPeriods} ${unit}s ago`
            },
        ],
        canNavigateForward: [
            (s) => [s.anchorDate, s.viewMode],
            (anchorDate, viewMode): boolean => {
                const now = dayjs()
                const currentPeriodStart = viewMode === 'week' ? now.startOf('isoWeek') : now.startOf('month')
                return anchorDate.isBefore(currentPeriodStart)
            },
        ],
    }),

    loaders(({ values }) => ({
        summaryStats: [
            null as InsightsSummaryStats | null,
            {
                loadSummaryStats: async () => {
                    const periodEnd =
                        values.viewMode === 'week'
                            ? values.anchorDate.add(1, 'week')
                            : values.anchorDate.add(1, 'month')
                    const effectiveEnd = periodEnd.isAfter(dayjs()) ? dayjs() : periodEnd
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
                            dateRange: {
                                date_from: values.anchorDate.startOf('day').format('YYYY-MM-DD HH:mm:ss'),
                                date_to: effectiveEnd.format('YYYY-MM-DD HH:mm:ss'),
                            },
                            filterTestAccounts: values.filterTestAccounts,
                        },
                    })
                    const row = response?.results?.[0]
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

    listeners(({ actions, values }) => ({
        setViewMode: ({ mode }) => {
            const start = mode === 'week' ? dayjs().startOf('isoWeek') : dayjs().startOf('month')
            actions.setAnchorDate(start)
        },
        navigateBack: () => {
            const unit = values.viewMode === 'week' ? 'week' : 'month'
            actions.setAnchorDate(values.anchorDate.subtract(1, unit))
        },
        navigateForward: () => {
            const unit = values.viewMode === 'week' ? 'week' : 'month'
            const next = values.anchorDate.add(1, unit)
            const now = dayjs()
            const currentPeriodStart = values.viewMode === 'week' ? now.startOf('isoWeek') : now.startOf('month')
            actions.setAnchorDate(next.isAfter(currentPeriodStart) ? currentPeriodStart : next)
        },
        setAnchorDate: () => {
            actions.loadSummaryStats()
        },
        setFilterTestAccounts: () => {
            actions.loadSummaryStats()
        },
        setFilterGroup: () => {
            actions.loadSummaryStats()
        },
    })),

    afterMount(({ actions }) => {
        actions.loadSummaryStats()
    }),
])
