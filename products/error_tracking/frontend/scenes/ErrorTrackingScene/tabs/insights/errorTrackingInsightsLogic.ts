import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import api from 'lib/api'
import { Dayjs, dayjs } from 'lib/dayjs'
import { teamLogic } from 'scenes/teamLogic'

import { HogQLQueryResponse, NodeKind } from '~/queries/schema/schema-general'
import { AnyPropertyFilter, FilterLogicalOperator, UniversalFiltersGroup } from '~/types'

import type { errorTrackingInsightsLogicType } from './errorTrackingInsightsLogicType'

function getPeriodStart(date: Dayjs, viewMode: InsightsViewMode, weekStartDay: number): Dayjs {
    if (viewMode === 'month') {
        return date.startOf('month')
    }
    dayjs.updateLocale('en', { weekStart: weekStartDay })
    return date.startOf('week')
}

export type InsightsViewMode = 'week' | 'month'

export type InsightsTrackableItem = 'summary_stats' | 'exception_volume' | 'crash_free_sessions'

const TRACKABLE_ITEMS: InsightsTrackableItem[] = ['summary_stats', 'exception_volume', 'crash_free_sessions']

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

    connect(() => ({
        values: [teamLogic, ['weekStartDay']],
    })),

    actions({
        setViewMode: (mode: InsightsViewMode) => ({ mode }),
        setAnchorDate: (date: Dayjs) => ({ date }),
        navigateBack: true,
        navigateForward: true,
        reload: true,
        setFilterGroup: (filterGroup: UniversalFiltersGroup) => ({ filterGroup }),
        setFilterTestAccounts: (filterTestAccounts: boolean) => ({ filterTestAccounts }),
        setLoadStartTime: (time: number) => ({ time }),
        reportItemLoaded: (item: InsightsTrackableItem, durationMs: number) => ({ item, durationMs }),
        incrementRefreshKey: true,
    }),

    reducers({
        viewMode: [
            'week' as InsightsViewMode,
            {
                setViewMode: (_, { mode }) => mode,
            },
        ],
        anchorDate: [
            dayjs().startOf('week') as Dayjs,
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
                const end =
                    viewMode === 'week' ? anchorDate.add(6, 'day') : anchorDate.add(1, 'month').subtract(1, 'day')
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
            (s) => [s.anchorDate, s.viewMode, s.weekStartDay],
            (anchorDate, viewMode, weekStartDay): string => {
                const now = dayjs()
                const unit = viewMode === 'week' ? 'week' : 'month'
                const currentPeriodStart = getPeriodStart(now, viewMode, weekStartDay)
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
            (s) => [s.anchorDate, s.viewMode, s.weekStartDay],
            (anchorDate, viewMode, weekStartDay): boolean => {
                const now = dayjs()
                const currentPeriodStart = getPeriodStart(now, viewMode, weekStartDay)
                return anchorDate.isBefore(currentPeriodStart)
            },
        ],
    }),

    loaders(({ actions, values }) => ({
        summaryStats: [
            null as InsightsSummaryStats | null,
            {
                loadSummaryStats: async () => {
                    const startTime = performance.now()
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
        setViewMode: ({ mode }) => {
            posthog.capture('error_tracking_insights_view_mode_changed', { view_mode: mode })
            actions.setAnchorDate(getPeriodStart(dayjs(), mode, values.weekStartDay))
        },
        navigateBack: () => {
            const unit = values.viewMode === 'week' ? 'week' : 'month'
            actions.setAnchorDate(values.anchorDate.subtract(1, unit))
        },
        navigateForward: () => {
            const unit = values.viewMode === 'week' ? 'week' : 'month'
            const next = values.anchorDate.add(1, unit)
            const currentPeriodStart = getPeriodStart(dayjs(), values.viewMode, values.weekStartDay)
            actions.setAnchorDate(next.isAfter(currentPeriodStart) ? currentPeriodStart : next)
        },
        setAnchorDate: () => {
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
                    view_mode: values.viewMode,
                    date_from: values.dateFrom,
                    date_to: values.dateTo,
                    relative_label: values.relativeDateLabel,
                    duration_ms_summary_stats: updatedTimings.summary_stats,
                    duration_ms_exception_volume: updatedTimings.exception_volume,
                    duration_ms_crash_free_sessions: updatedTimings.crash_free_sessions,
                })
            }
        },
    })),

    afterMount(({ actions, values }) => {
        posthog.capture('error_tracking_insights_viewed')
        actions.setAnchorDate(getPeriodStart(dayjs(), values.viewMode, values.weekStartDay))
    }),
])
