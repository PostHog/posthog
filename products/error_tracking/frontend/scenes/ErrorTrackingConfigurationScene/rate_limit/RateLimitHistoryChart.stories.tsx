import { Meta, StoryObj } from '@storybook/react'
import { ReactNode } from 'react'

import { dayjs } from 'lib/dayjs'

import { RateLimitHistoryBucket } from './rateLimitConfigLogic'
import { RateLimitHistoryChart } from './RateLimitHistoryChart'
import { getBucketTimeline } from './RateLimitSimulationChart'

const meta: Meta<typeof RateLimitHistoryChart> = {
    title: 'ErrorTracking/RateLimitHistoryChart',
    component: RateLimitHistoryChart,
    parameters: {
        layout: 'centered',
        testOptions: { snapshotBrowsers: ['chromium'] },
    },
}
export default meta

type Story = StoryObj<typeof RateLimitHistoryChart>

const BUCKET_MINUTES = 60

/** Deterministic recorded/dropped/bypassed counts aligned to the chart's own bucket timeline —
 *  the rendered bars are stable across runs even though the timeline is anchored to `Date.now()`
 *  (the bucket dates themselves never render: the x-axis is hidden). */
function exampleHistory(): RateLimitHistoryBucket[] {
    return getBucketTimeline(BUCKET_MINUTES).map((ms, i) => {
        const wave = Math.max(0, Math.round(70 + 50 * Math.sin(i / 7)))
        const overage = Math.max(0, Math.round(30 * Math.sin(i / 4) - 12))
        return {
            bucket: dayjs(ms).toISOString(),
            recorded: wave,
            dropped: overage,
            bypassed: i % 9 === 0 ? 5 : 0,
        }
    })
}

function Stage({ children }: { children: ReactNode }): JSX.Element {
    // eslint-disable-next-line react/forbid-dom-props
    return <div style={{ width: 760 }}>{children}</div>
}

/** Stacked recorded/dropped/bypassed bars with the danger/warning series colors. */
export const WithActivity: Story = {
    render: () => (
        <Stage>
            <RateLimitHistoryChart history={exampleHistory()} bucketMinutes={BUCKET_MINUTES} />
        </Stage>
    ),
}

export const Empty: Story = {
    render: () => (
        <Stage>
            <RateLimitHistoryChart history={[]} bucketMinutes={BUCKET_MINUTES} />
        </Stage>
    ),
}
