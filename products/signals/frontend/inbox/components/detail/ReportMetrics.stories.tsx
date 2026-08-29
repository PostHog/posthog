import type { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'
import { NodeKind, type InsightVizNode, type TrendsQuery } from '~/queries/schema/schema-general'
import { BaseMathType, ChartDisplayType } from '~/types'

import type { ReportMetricApi } from 'products/signals/frontend/generated/api.schemas'

import { ReportMetrics } from './ReportMetrics'

const dates = ['2026-08-23', '2026-08-24', '2026-08-25', '2026-08-26', '2026-08-27', '2026-08-28', '2026-08-29']

function eventMetricQuery(
    event: string,
    customName: string,
    math: BaseMathType = BaseMathType.TotalCount
): InsightVizNode<TrendsQuery> {
    return {
        kind: NodeKind.InsightVizNode,
        source: {
            kind: NodeKind.TrendsQuery,
            dateRange: { date_from: '-7d', date_to: null },
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

const affectedUsersQuery = eventMetricQuery('$autocapture', 'Users affected', BaseMathType.UniqueUsers)
const deadClicksQuery = eventMetricQuery('dead_click', 'Dead clicks')
const errorsQuery = eventMetricQuery('$exception', 'Errors')
const conversionQuery: InsightVizNode<TrendsQuery> = {
    kind: NodeKind.InsightVizNode,
    source: {
        kind: NodeKind.TrendsQuery,
        dateRange: { date_from: '-7d', date_to: null },
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

const liveMetricResults: Record<string, { aggregatedValue: number; data: number[]; label: string }> = {
    $autocapture: {
        aggregatedValue: 1248,
        data: [132, 184, 211, 196, 249, 238, 263],
        label: 'Users affected',
    },
    dead_click: {
        aggregatedValue: 3912,
        data: [451, 522, 487, 538, 604, 671, 639],
        label: 'Dead clicks',
    },
    conversion: {
        aggregatedValue: 0.34,
        data: [0.31, 0.33, 0.32, 0.35, 0.34, 0.36, 0.34],
        label: 'Conversion after the observation',
    },
    $exception: {
        aggregatedValue: 0,
        data: [0, 0, 0, 0, 0, 0, 0],
        label: 'Errors',
    },
}

const metrics: ReportMetricApi[] = [
    {
        metric_id: 'affected-users',
        title: 'Users affected',
        kind: 'affected_users',
        role: 'primary',
        value: 1196,
        value_at: '2026-08-29T12:00:00Z',
        value_format: 'count',
        unit: 'users',
        query: affectedUsersQuery,
        caption: 'Unique users who encountered this observation in the last 7 days.',
        comparison: { value: 832, label: 'Previous 7 days' },
    },
    {
        metric_id: 'dead-clicks',
        title: 'Dead clicks',
        kind: 'occurrences',
        role: 'supporting',
        value: 3912,
        value_at: '2026-08-29T12:00:00Z',
        value_format: 'count',
        unit: 'clicks',
        query: deadClicksQuery,
        caption: 'Median of 3 per affected user.',
        comparison: null,
    },
    {
        metric_id: 'conversion',
        title: 'Conversion after the observation',
        kind: 'conversion_rate',
        role: 'supporting',
        value: 0.34,
        value_at: '2026-08-29T12:00:00Z',
        value_format: 'percentage_scaled',
        unit: null,
        query: conversionQuery,
        caption: null,
        comparison: { value: 0.71, label: 'Before the observation' },
    },
    {
        metric_id: 'errors',
        title: 'Errors',
        kind: 'occurrences',
        role: 'supporting',
        value: 0,
        value_at: '2026-08-29T12:00:00Z',
        value_format: 'count',
        unit: 'errors',
        query: errorsQuery,
        caption: 'No matching exceptions were captured.',
        comparison: null,
    },
]

const meta: Meta<typeof ReportMetrics> = {
    title: 'Scenes-App/Inbox/Report metrics',
    component: ReportMetrics,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-08-29',
    },
    decorators: [
        mswDecorator({
            post: {
                '/api/environments/:team_id/query/:kind/': async ({ request }) => {
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
                                    days: dates,
                                    labels: dates,
                                    aggregated_value: result.aggregatedValue,
                                },
                            ],
                        },
                    ]
                },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof ReportMetrics>

export const Wide: Story = {
    args: { reportId: 'report-with-metrics', metrics },
    render: (args) => (
        <div className="min-h-screen bg-primary p-6">
            <div className="mx-auto max-w-4xl">
                <ReportMetrics {...args} />
            </div>
        </div>
    ),
}

export const Narrow: Story = {
    args: { reportId: 'narrow-report-with-metrics', metrics },
    render: (args) => (
        <div className="min-h-screen bg-primary p-6">
            <div className="w-96 max-w-full">
                <ReportMetrics {...args} />
            </div>
        </div>
    ),
}

export const LiveSupportingMetric: Story = {
    args: {
        reportId: 'report-with-live-supporting-metric',
        metrics: [{ ...metrics[0], role: 'supporting' }],
    },
    render: (args) => (
        <div className="min-h-screen bg-primary p-6">
            <div className="mx-auto max-w-md">
                <ReportMetrics {...args} />
            </div>
        </div>
    ),
}
