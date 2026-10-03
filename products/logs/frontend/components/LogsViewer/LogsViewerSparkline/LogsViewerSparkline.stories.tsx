import { Meta, StoryObj } from '@storybook/react'

import { OTHER_BREAKDOWN_LABEL } from 'products/logs/frontend/sparklineOtherBreakdown'

import { LogsSparkline, LogsSparklineData } from './index'

const BUCKET_SECONDS = 90
const BUCKETS = 48
const FIRST_BUCKET = Date.parse('2026-08-06T09:00:00Z')

const SEVERITY_PROFILES: { name: string; color: string; baseline: number }[] = [
    { name: 'info', color: 'brand-blue', baseline: 320 },
    { name: 'warn', color: 'warning', baseline: 90 },
    { name: 'error', color: 'danger', baseline: 40 },
    { name: OTHER_BREAKDOWN_LABEL, color: 'muted', baseline: 25 },
]

function buildSparklineData(): LogsSparklineData {
    const dates = Array.from({ length: BUCKETS }, (_, bucket) =>
        new Date(FIRST_BUCKET + bucket * BUCKET_SECONDS * 1000).toISOString()
    )
    return {
        dates,
        data: SEVERITY_PROFILES.map(({ name, color, baseline }) => ({
            name,
            color,
            values: dates.map((_, bucket) => Math.round(baseline * (1 + 0.4 * Math.sin(bucket / 5)))),
        })),
    }
}

const meta: Meta<typeof LogsSparkline> = {
    title: 'Scenes-App/Logs/Sparkline',
    component: LogsSparkline,
    args: {
        sparklineData: buildSparklineData(),
        sparklineLoading: false,
        displayTimezone: 'UTC',
        collapsed: false,
    },
    parameters: {
        layout: 'padded',
        viewMode: 'story',
        mockDate: '2026-08-06',
        // Bars paint asynchronously (ResizeObserver, then rAF); chromium alone keeps the snapshot stable.
        testOptions: { snapshotBrowsers: ['chromium'] },
    },
    render: (args) => (
        <div className="w-[900px]">
            <LogsSparkline {...args} />
        </div>
    ),
}

export default meta

type Story = StoryObj<typeof LogsSparkline>

export const VolumeBySeverity: Story = {}

export const WithIncompleteBuckets: Story = {
    args: {
        incompleteBarIndices: [45, 46, 47],
    },
}

export const WithVisibleRowRange: Story = {
    args: {
        visibleRowDateRange: {
            date_from: new Date(FIRST_BUCKET + 12 * BUCKET_SECONDS * 1000).toISOString(),
            date_to: new Date(FIRST_BUCKET + 22 * BUCKET_SECONDS * 1000).toISOString(),
        },
    },
}
