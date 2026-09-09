import type { Meta, StoryObj } from '@storybook/react'

import { dayjs } from 'lib/dayjs'

import type { VisionQuotaApi } from '../../generated/api.schemas'
import { verdictColorVar } from '../../utils/spendVerdict'
import type { SpendSeries } from '../visionUsageLogic'
import { SpendTrajectoryChart } from './SpendTrajectoryChart'

const meta: Meta<typeof SpendTrajectoryChart> = {
    title: 'Scenes-App/Replay Vision/SpendTrajectoryChart',
    component: SpendTrajectoryChart,
    parameters: {
        layout: 'centered',
        mockDate: '2026-05-12',
        testOptions: { snapshotBrowsers: ['chromium'] },
    },
    decorators: [
        (Story) => (
            // eslint-disable-next-line react/forbid-dom-props
            <div style={{ width: 720 }}>
                <Story />
            </div>
        ),
    ],
}
export default meta

type Story = StoryObj<typeof SpendTrajectoryChart>

const quota: VisionQuotaApi = {
    credit_limit: 10_000,
    credits_used: 2_400,
    remaining: 7_600,
    exhausted: false,
    projected_monthly_credits: 5_200,
    scanners_monthly_credits: 5_200,
    backfills_committed_credits: 0,
    free_monthly_credits: 2_500,
    credits_settled: 2_400,
    credits_reserved: 0,
    period_start: '2026-05-01T00:00:00Z',
    period_end: '2026-06-01T00:00:00Z',
}

const dailyCredits: SpendSeries = [150, 190, 230, 260, 90, 80, 250, 280, 310, 120, 440].map((credits, i) => ({
    date: `2026-05-${String(i + 1).padStart(2, '0')}`,
    credits,
}))

export const OnTrack: Story = {
    args: {
        quota,
        dailyCredits,
        projectedTotal: 5_900,
        capReachDate: null,
        statusVar: verdictColorVar('safe'),
    },
}

export const HitsTheLimit: Story = {
    args: {
        quota: { ...quota, scanners_monthly_credits: 16_000, projected_monthly_credits: 16_000 },
        dailyCredits,
        projectedTotal: 10_000,
        capReachDate: dayjs.utc('2026-05-26T12:00:00Z'),
        statusVar: verdictColorVar('danger'),
    },
}

export const PausedAtTheLimit: Story = {
    args: {
        quota: { ...quota, credits_used: 10_000, credits_settled: 10_000, remaining: 0, exhausted: true },
        dailyCredits: dailyCredits.map((day) => ({ ...day, credits: day.credits * 4 })),
        projectedTotal: 10_000,
        capReachDate: null,
        statusVar: verdictColorVar('paused'),
    },
}

export const NoLimit: Story = {
    args: {
        quota: { ...quota, credit_limit: null, remaining: null },
        dailyCredits,
        projectedTotal: 5_900,
        capReachDate: null,
        statusVar: verdictColorVar('uncapped'),
    },
}
