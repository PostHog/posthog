import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { InsightVizStory } from 'scenes/insights/__mocks__/createInsightVizStory'

import __trendsMetric from '~/mocks/fixtures/api/projects/team_id/insights/trendsMetric.json'

import { MetricCard } from './Metric'

type Story = StoryObj<{}>

const meta: Meta = {
    title: 'Insights/Metric',
    component: MetricCard,
    parameters: {
        layout: 'centered',
        mockDate: '2022-04-01',
        featureFlags: [FEATURE_FLAGS.METRIC_INSIGHT],
        testOptions: {
            snapshotBrowsers: ['chromium'],
            waitForSelector: '.Metric canvas',
        },
    },
}
export default meta

export const Default: Story = {
    render: () => <InsightVizStory insight={__trendsMetric as any} />,
}

// 13 monthly buckets, so the first and last both fall on April 1. Display text repeats there while the
// bucket keys stay unique, which is the case that collapses the last point onto the first whenever the
// sparkline is keyed on display text.
const MONTHLY_DAYS = [
    '2021-04-01',
    '2021-05-01',
    '2021-06-01',
    '2021-07-01',
    '2021-08-01',
    '2021-09-01',
    '2021-10-01',
    '2021-11-01',
    '2021-12-01',
    '2022-01-01',
    '2022-02-01',
    '2022-03-01',
    '2022-04-01',
]
const MONTHLY_DATA = [1240, 1655, 1980, 2410, 2295, 2870, 3320, 3105, 3890, 4260, 4515, 5090, 5480]

const yearSpanInsight = {
    ...__trendsMetric,
    result: [
        {
            ...(__trendsMetric.result[0] as Record<string, unknown>),
            days: MONTHLY_DAYS,
            labels: MONTHLY_DAYS,
            data: MONTHLY_DATA,
            count: MONTHLY_DATA.reduce((sum, value) => sum + value, 0),
        },
    ],
    query: {
        ...__trendsMetric.query,
        source: {
            ...(__trendsMetric.query as any).source,
            dateRange: { date_from: '-12m' },
            interval: 'month',
        },
    },
}

export const SpanningAYear: Story = {
    render: () => <InsightVizStory insight={yearSpanInsight as any} />,
}
