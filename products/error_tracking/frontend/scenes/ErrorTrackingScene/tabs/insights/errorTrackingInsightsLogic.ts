import { actions, kea, listeners, path, reducers, selectors } from 'kea'

import { Dayjs, dayjs } from 'lib/dayjs'

import type { errorTrackingInsightsLogicType } from './errorTrackingInsightsLogicType'

export type InsightsViewMode = 'week' | 'month'

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
    }),

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
    })),

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
        canNavigateForward: [
            (s) => [s.anchorDate, s.viewMode],
            (anchorDate, viewMode): boolean => {
                const now = dayjs()
                const currentPeriodStart = viewMode === 'week' ? now.startOf('isoWeek') : now.startOf('month')
                return anchorDate.isBefore(currentPeriodStart)
            },
        ],
    }),
])
