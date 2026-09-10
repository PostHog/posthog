import { Meta, StoryObj } from '@storybook/react'
import { ReactNode } from 'react'

import { dayjs } from 'lib/dayjs'

import { ExceptionVolumeBucket } from './rateLimitConfigLogic'
import { getBucketTimeline, RateLimitSimulationChart } from './RateLimitSimulationChart'

const meta: Meta<typeof RateLimitSimulationChart> = {
    title: 'ErrorTracking/RateLimitSimulationChart',
    component: RateLimitSimulationChart,
    parameters: {
        layout: 'centered',
        testOptions: { snapshotBrowsers: ['chromium'] },
    },
}
export default meta

type Story = StoryObj<typeof RateLimitSimulationChart>

const BUCKET_MINUTES = 60

/** Deterministic wave of exception counts aligned to the chart's own bucket timeline — the
 *  rendered bars are stable across runs even though the timeline is anchored to `Date.now()`
 *  (the bucket dates themselves never render: the x-axis is hidden). */
function exampleVolume(): ExceptionVolumeBucket[] {
    return getBucketTimeline(BUCKET_MINUTES).map((ms, i) => ({
        bucket: dayjs(ms).toISOString(),
        count: Math.max(0, Math.round(60 + 55 * Math.sin(i / 6) + 20 * Math.sin(i / 2))),
    }))
}

function Stage({ children }: { children: ReactNode }): JSX.Element {
    // eslint-disable-next-line react/forbid-dom-props
    return <div style={{ width: 760 }}>{children}</div>
}

/** Stacked within/above-limit split with the goal line marking the configured limit. */
export const WithLimit: Story = {
    render: () => (
        <Stage>
            <RateLimitSimulationChart volume={exampleVolume()} rateLimit={80} bucketMinutes={BUCKET_MINUTES} />
        </Stage>
    ),
}

/** No limit configured — a plain single-series bar chart, no goal line. */
export const NoLimit: Story = {
    render: () => (
        <Stage>
            <RateLimitSimulationChart volume={exampleVolume()} rateLimit={null} bucketMinutes={BUCKET_MINUTES} />
        </Stage>
    ),
}
