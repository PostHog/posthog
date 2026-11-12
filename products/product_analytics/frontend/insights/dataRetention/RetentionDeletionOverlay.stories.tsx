import { Meta, StoryObj } from '@storybook/react'

import {
    type Series,
    TimeSeriesBarChart,
    TimeSeriesLineChart,
    type TimeSeriesLineChartConfig,
} from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'

import { mswDecorator } from '~/mocks/browser'

import type { EventsRetentionApi } from 'products/product_analytics/frontend/generated/api.schemas'

import { RetentionDeletionOverlay } from './RetentionDeletionOverlay'

const RETENTION: EventsRetentionApi = {
    retention_months: null,
    retained_from: null,
    docs_url: 'https://posthog.com/docs/data/events-retention',
    project_retention_months: 12,
    next_deletion_on: '2026-12-01',
    next_deletion_before: '2025-10-01',
    scheduled_pass_on: null,
    first_pass_on: '2027-03-01',
    default_period_deletes: false,
    organization_retention_months: null,
    default_retention_months: 84,
    default_is_grandfathered: true,
    plan_retention_months: 84,
    min_retention_months: 1,
    max_retention_months: 84,
    retention_months_choices: [1, 3, 12, 24, 36, 60, 84],
    next_monthly_cleanup_on: '2026-12-01',
}

const LABELS = [
    '2025-09-01',
    '2025-09-08',
    '2025-09-15',
    '2025-09-22',
    '2025-09-29',
    '2025-10-06',
    '2025-10-13',
    '2025-10-20',
    '2025-10-27',
    '2025-11-03',
    '2025-11-10',
    '2025-11-17',
]

const SERIES: Series[] = [
    { key: 'pageviews', label: 'Pageview', data: [820, 910, 870, 990, 1040, 1010, 1130, 1090, 1180, 1220, 1170, 1260] },
]

const CONFIG: TimeSeriesLineChartConfig = { xAxis: { timezone: 'UTC', interval: 'week' } }

const meta: Meta = {
    title: 'Insights/RetentionDeletionOverlay',
    component: RetentionDeletionOverlay,
    parameters: {
        layout: 'centered',
        testOptions: { snapshotBrowsers: [], waitForSelector: '[data-attr="retention-deletion-overlay"]' },
    },
    decorators: [mswDecorator({ get: { '/api/projects/:team_id/events_retention/': RETENTION } })],
}
export default meta

type Story = StoryObj<{}>

function Stage({ children }: { children: React.ReactNode }): JSX.Element {
    return <div className="flex h-[360px] w-[720px] flex-col">{children}</div>
}

function LineChart(): JSX.Element {
    const theme = useChartTheme()
    return (
        <Stage>
            <TimeSeriesLineChart series={SERIES} labels={LABELS} theme={theme} config={CONFIG}>
                <RetentionDeletionOverlay isStickiness={false} querySource={null} compareFilter={null} />
            </TimeSeriesLineChart>
        </Stage>
    )
}

function BarChart(): JSX.Element {
    const theme = useChartTheme()
    return (
        <Stage>
            <TimeSeriesBarChart series={SERIES} labels={LABELS} theme={theme} config={CONFIG}>
                <RetentionDeletionOverlay isStickiness={false} querySource={null} compareFilter={null} />
            </TimeSeriesBarChart>
        </Stage>
    )
}

export const Line: Story = { render: () => <LineChart /> }

export const Bar: Story = { render: () => <BarChart /> }
