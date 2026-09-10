import { NodeKind, type InsightVizNode, type TrendsQuery } from '~/queries/schema/schema-general'
import { BaseMathType, ChartDisplayType } from '~/types'

import type { ReportMetricApi } from 'products/signals/frontend/generated/api.schemas'

const dates = [
    '2026-08-16',
    '2026-08-17',
    '2026-08-18',
    '2026-08-19',
    '2026-08-20',
    '2026-08-21',
    '2026-08-22',
    '2026-08-23',
    '2026-08-24',
    '2026-08-25',
    '2026-08-26',
    '2026-08-27',
    '2026-08-28',
    '2026-08-29',
]

// A month of daily buckets, so a story can exercise a window several times longer than the default.
const sparseDates = Array.from({ length: 30 }, (_, index) => {
    const day = new Date(Date.UTC(2026, 6, 31 + index))
    return day.toISOString().slice(0, 10)
})

function eventMetricQuery(
    event: string,
    customName: string,
    math: BaseMathType = BaseMathType.TotalCount,
    dateFrom: string = '-14d'
): InsightVizNode<TrendsQuery> {
    return {
        kind: NodeKind.InsightVizNode,
        source: {
            kind: NodeKind.TrendsQuery,
            dateRange: { date_from: dateFrom, date_to: null },
            interval: 'day',
            series: [
                {
                    kind: NodeKind.EventsNode,
                    event,
                    name: event,
                    custom_name: customName,
                    math,
                },
            ],
            trendsFilter: { display: ChartDisplayType.ActionsBar },
        },
    }
}

const conversionQuery: InsightVizNode<TrendsQuery> = {
    kind: NodeKind.InsightVizNode,
    source: {
        kind: NodeKind.TrendsQuery,
        dateRange: { date_from: '-14d', date_to: null },
        interval: 'day',
        series: [
            {
                kind: NodeKind.EventsNode,
                event: 'checkout_completed',
                name: 'checkout_completed',
                custom_name: 'Completed checkout',
                math: BaseMathType.UniqueUsers,
            },
            {
                kind: NodeKind.EventsNode,
                event: 'checkout_started',
                name: 'checkout_started',
                custom_name: 'Started checkout',
                math: BaseMathType.UniqueUsers,
            },
        ],
        trendsFilter: {
            display: ChartDisplayType.ActionsBar,
            formula: 'A / B',
            aggregationAxisFormat: 'percentage_scaled',
        },
    },
}

const liveMetricResults: Record<string, { aggregatedValue: number; data: number[]; label: string; days?: string[] }> = {
    $autocapture: {
        aggregatedValue: 1248,
        data: [88, 96, 104, 99, 121, 118, 132, 132, 184, 211, 196, 249, 238, 263],
        label: 'Users affected',
    },
    dead_click: {
        aggregatedValue: 3912,
        data: [312, 348, 331, 372, 396, 401, 388, 451, 522, 487, 538, 604, 671, 639],
        label: 'Dead clicks',
    },
    conversion: {
        aggregatedValue: 0.34,
        data: [0.38, 0.37, 0.39, 0.36, 0.38, 0.37, 0.35, 0.31, 0.33, 0.32, 0.35, 0.34, 0.36, 0.34],
        label: 'Conversion after the observation',
    },
    $exception: {
        aggregatedValue: 0,
        data: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        label: 'Errors',
    },
    upload_failed: {
        aggregatedValue: 5,
        data: [3, 1, 1, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0],
        days: sparseDates,
        label: 'People who hit the overwrite',
    },
}

/** One primary affected-users metric and three supporting facts, with saved snapshots and live queries. */
export const reportMetricsFixture: ReportMetricApi[] = [
    {
        metric_id: 'affected-users',
        title: 'People who clicked Create key and got nothing back',
        kind: 'affected_users',
        role: 'primary',
        value: 1196,
        value_at: '2026-08-29T12:00:00Z',
        series: liveMetricResults.$autocapture.data,
        value_format: 'count',
        unit: 'users',
        query: eventMetricQuery('$autocapture', 'Create key click', BaseMathType.UniqueUsers),
        caption: 'Excludes internal users and test accounts.',
        comparison: { value: 832, label: 'Previous 14 days' },
    },
    {
        metric_id: 'dead-clicks',
        title: 'Dead clicks on the Create key button',
        kind: 'occurrences',
        role: 'supporting',
        value: 3912,
        value_at: '2026-08-29T12:00:00Z',
        series: null,
        value_format: 'count',
        unit: 'clicks',
        query: eventMetricQuery('dead_click', 'Dead clicks'),
        caption: 'Median of 3 per affected user.',
        comparison: null,
    },
    {
        metric_id: 'conversion',
        title: 'Share of people who left settings with a key',
        kind: 'conversion_rate',
        role: 'supporting',
        value: 0.34,
        value_at: '2026-08-29T12:00:00Z',
        series: null,
        value_format: 'percentage_scaled',
        unit: null,
        query: conversionQuery,
        caption: null,
        comparison: { value: 0.71, label: 'Before the observation' },
    },
    {
        metric_id: 'errors',
        title: 'Exceptions captured on the API keys page',
        kind: 'occurrences',
        role: 'supporting',
        value: 0,
        value_at: '2026-08-29T12:00:00Z',
        series: null,
        value_format: 'count',
        unit: 'errors',
        query: eventMetricQuery('$exception', 'Errors'),
        caption: 'No matching exceptions were captured.',
        comparison: null,
    },
]

/** A rare event over a month: single-digit daily counts, most of them zero, and long stretches of nothing. */
export const reportSparseMetricFixture: ReportMetricApi = {
    metric_id: 'upload-overwrites',
    title: 'People who hit the overwrite',
    kind: 'affected_users',
    role: 'primary',
    value: 5,
    value_at: '2026-08-29T12:00:00Z',
    series: liveMetricResults.upload_failed.data,
    value_format: 'count',
    unit: 'users',
    query: eventMetricQuery('upload_failed', 'Upload overwrite', BaseMathType.UniqueUsers, '-30d'),
    caption: 'Counted once per person, so the daily bars add up to more than the total.',
    comparison: null,
}

/** A primary metric whose query the viewer cannot see, so only the saved snapshot is left to show. */
export const reportSavedValueMetricFixture: ReportMetricApi = {
    metric_id: 'checkout-duration',
    title: 'Time from the first Create key click to a saved key',
    kind: 'duration',
    role: 'primary',
    value: 287,
    value_at: '2026-08-28T12:00:00Z',
    series: null,
    value_format: 'duration',
    unit: 's',
    query: null,
    caption: 'Median across the people who hit this observation.',
    comparison: { value: 199, label: 'Previous 14 days' },
}

/** Answers the query endpoint for every metric in `reportMetricsFixture`, keyed on the first series' event. */
export async function reportMetricQueryHandler({ request }: { request: Request }): Promise<[number, unknown]> {
    const body = (await request.json()) as {
        query?: {
            series?: Array<{ custom_name?: string; event?: string; math?: string; name?: string }>
            trendsFilter?: { formula?: string }
        }
    }
    const series = body.query?.series?.[0]
    const resultKey = body.query?.trendsFilter?.formula ? 'conversion' : series?.event
    const result = liveMetricResults[resultKey ?? ''] ?? liveMetricResults.$autocapture

    return [
        200,
        {
            result: [
                {
                    action: {
                        id: series?.event,
                        type: 'events',
                        order: 0,
                        name: series?.name,
                        custom_name: result.label,
                        math: series?.math,
                        properties: {},
                    },
                    label: result.label,
                    count: result.data.at(-1) ?? 0,
                    data: result.data,
                    days: result.days ?? dates,
                    labels: result.days ?? dates,
                    aggregated_value: result.aggregatedValue,
                },
            ],
        },
    ]
}
