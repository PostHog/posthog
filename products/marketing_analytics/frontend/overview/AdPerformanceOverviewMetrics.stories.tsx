import type { Meta, StoryObj } from '@storybook/react'

import type { OverviewMetricCardItem } from '~/queries/nodes/OverviewGrid/OverviewMetricCardGrid'

import { AdPerformanceOverviewMetrics } from './AdPerformanceOverviewMetrics'

const items: OverviewMetricCardItem[] = [
    { key: 'Cost', value: 1800, previous: 1500, changeFromPreviousPct: 20, kind: 'currency', isIncreaseBad: true },
    { key: 'Clicks', value: 4200, previous: 3500, changeFromPreviousPct: 20, kind: 'unit' },
    { key: 'Impressions', value: 90000, previous: 75000, changeFromPreviousPct: 20, kind: 'unit' },
    { key: 'Reported Conversions', value: 60, previous: 50, changeFromPreviousPct: 20, kind: 'unit' },
    { key: 'Reported Conversion Value', value: 3600, previous: 3000, changeFromPreviousPct: 20, kind: 'currency' },
    { key: 'CPC', value: 0.43, previous: 0.43, changeFromPreviousPct: 0, kind: 'currency', isIncreaseBad: true },
    { key: 'CTR', value: 4.67, previous: 4.67, changeFromPreviousPct: 0, kind: 'percentage' },
    {
        key: 'Cost per Reported Conversions',
        value: 30,
        previous: 30,
        changeFromPreviousPct: 0,
        kind: 'currency',
        isIncreaseBad: true,
    },
    { key: 'Reported ROAS', value: 2, previous: 2, changeFromPreviousPct: 0, kind: 'unit' },
    { key: 'Trial started', value: 80, previous: 64, changeFromPreviousPct: 25, kind: 'unit' },
    {
        key: 'Cost Per Trial started',
        value: 22.5,
        previous: 23.44,
        changeFromPreviousPct: -4,
        kind: 'currency',
        isIncreaseBad: true,
    },
    { key: 'Subscription started', value: 20, previous: 16, changeFromPreviousPct: 25, kind: 'unit' },
    {
        key: 'Cost Per Subscription started',
        value: 90,
        previous: 93.75,
        changeFromPreviousPct: -4,
        kind: 'currency',
        isIncreaseBad: true,
    },
]

const meta: Meta<typeof AdPerformanceOverviewMetrics> = {
    title: 'Scenes-App/Marketing Analytics/Overview metrics',
    component: AdPerformanceOverviewMetrics,
    parameters: { layout: 'padded' },
    args: { items, loading: false, numSkeletons: 13, viewKey: 'overview-metrics-story', labelFromKey: (key) => key },
}
export default meta

type Story = StoryObj<typeof AdPerformanceOverviewMetrics>

export const Default: Story = {}

export const Narrow: Story = {
    args: { viewKey: 'overview-metrics-narrow-story' },
    decorators: [
        (Story) => (
            <div className="max-w-lg">
                <Story />
            </div>
        ),
    ],
}

export const Loading: Story = {
    args: { viewKey: 'overview-metrics-loading-story', items: [], loading: true },
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
}

export const WithoutGoals: Story = {
    args: { viewKey: 'overview-metrics-no-goals-story', items: items.slice(0, 9) },
}
