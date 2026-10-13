import { dayjs } from 'lib/dayjs'

import { NodeKind, RetentionQueryResponse, TrendsQueryResponse } from '~/queries/schema/schema-general'
import { TrendResult } from '~/types'

import { HomeTabChartOption } from './homeTabDefaultTiles'

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
        return undefined
    }

    const results: TrendResult[] = breakdowns.map(([label, count]) => ({
        action: {
            id: source.series[0].kind === NodeKind.EventsNode ? (source.series[0].event ?? null) : null,
            type: 'events',
            order: 0,
            name: 'Sample',
            math: source.series[0].math,
        },
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
