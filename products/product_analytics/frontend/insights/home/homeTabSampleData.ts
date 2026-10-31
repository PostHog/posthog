import { dayjs } from 'lib/dayjs'
import { dateStringToDayJs } from 'lib/utils/dateFilters'

import { NodeKind, RetentionQueryResponse, TrendsQuery, TrendsQueryResponse } from '~/queries/schema/schema-general'
import { CompareLabelType, TrendResult } from '~/types'

import type { HomeTabMetricKey } from './homeTabDefaultLogic'
import { HomeTabChartOption } from './homeTabDefaultTiles'

const METRIC_VALUES: Record<HomeTabMetricKey, number[]> = {
    active_users: [340, 410, 380, 520, 460, 610, 580],
    sessions: [480, 560, 530, 720, 640, 850, 810],
    new_users: [80, 110, 95, 140, 120, 170, 150],
    session_duration: [145, 160, 152, 180, 165, 195, 184],
    daily_active_users: [340, 410, 380, 520, 460, 610, 580],
}

export function getHomeTabSampleStatData(metric: HomeTabMetricKey, query: TrendsQuery): TrendsQueryResponse {
    const values = METRIC_VALUES[metric]
    const interval = query.interval ?? 'day'
    const unit = interval === 'quarter' ? 'month' : interval
    const step = interval === 'quarter' ? 3 : 1
    const end = (dateStringToDayJs(query.dateRange?.date_to ?? null) ?? dayjs()).startOf(unit)
    const days = values.map((_, index) => end.subtract((values.length - index) * step, unit).toISOString())

    return {
        results: Array.from({ length: query.compareFilter?.compare ? 2 : 1 }, (_, index): TrendResult => {
            const data = values.map((value) => Math.round(value * (index === 0 ? 1 : 0.84)))
            const total = data.reduce((sum, value) => sum + value, 0)
            const count = metric === 'session_duration' || metric === 'daily_active_users' ? total / data.length : total
            return {
                order: 0,
                label: 'Sample',
                count,
                aggregated_value: count,
                data,
                days,
                labels: days,
                ...(query.compareFilter?.compare
                    ? {
                          compare: true,
                          compare_label: index === 0 ? CompareLabelType.Current : CompareLabelType.Previous,
                      }
                    : {}),
            }
        }),
    }
}

const BREAKDOWNS: Record<string, [string, number][]> = {
    users_by_country: [
        ['US', 640],
        ['GB', 280],
        ['DE', 210],
        ['IN', 180],
        ['BR', 120],
        ['AU', 90],
    ],
    sessions_by_device: [
        ['Desktop', 640],
        ['Mobile', 280],
        ['Tablet', 80],
    ],
    top_pages: [
        ['/', 1280],
        ['/pricing', 940],
        ['/docs', 720],
        ['/signup', 480],
        ['/blog', 260],
    ],
    top_screens: [
        ['Home', 1280],
        ['Search', 940],
        ['Settings', 720],
        ['Profile', 480],
    ],
    top_events: [
        ['$pageview', 1280],
        ['$autocapture', 940],
        ['$screen', 720],
        ['signed_up', 480],
        ['purchase', 260],
    ],
}

export function getHomeTabSampleData(
    option: HomeTabChartOption
): TrendsQueryResponse | RetentionQueryResponse | undefined {
    const source = option.query.source
    if (source.kind === NodeKind.RetentionQuery) {
        const intervals = source.retentionFilter.totalIntervals ?? 5
        const end = dayjs().startOf('week').subtract(1, 'week')
        return {
            results: Array.from({ length: intervals }, (_, cohortIndex) => {
                const size = 240 + cohortIndex * 30
                return {
                    label: `Week ${cohortIndex}`,
                    date: end.subtract(intervals - cohortIndex - 1, 'week').toISOString(),
                    values: Array.from({ length: intervals - cohortIndex }, (_, interval) => ({
                        count: interval === 0 ? size : Math.round(size * 0.6 * 0.75 ** (interval - 1)),
                    })),
                }
            }),
        }
    }

    const breakdowns = BREAKDOWNS[option.key]
    if (!breakdowns) {
        return option.key in METRIC_VALUES
            ? getHomeTabSampleStatData(option.key as HomeTabMetricKey, source)
            : undefined
    }

    const results: TrendResult[] = breakdowns.map(([label, count]) => ({
        order: 0,
        label,
        breakdown_value: label,
        count,
        aggregated_value: count,
        data: [count],
        days: [dayjs().format('YYYY-MM-DD')],
        labels: ['Sample'],
    }))
    return { results }
}
