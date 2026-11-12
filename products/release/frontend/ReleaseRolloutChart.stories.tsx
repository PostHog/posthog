import type { Meta, StoryObj } from '@storybook/react'

import { dayjs } from 'lib/dayjs'

import { RolloutStep } from './releaseRollout'
import { ReleaseRolloutChart } from './ReleaseRolloutChart'

const START = dayjs('2026-10-26T00:00:00Z')
const DAYS = 30
const at = (day: number): string => START.add(day, 'day').toISOString()

const step = (from: number, to: number, percent: number, upcoming = false): RolloutStep => ({
    from: at(from),
    to: at(to),
    percent,
    label: percent === 100 ? 'Everyone' : `${percent}%`,
    upcoming,
})

const meta: Meta<typeof ReleaseRolloutChart> = {
    title: 'Scenes-App/Releases/Rollout chart',
    component: ReleaseRolloutChart,
    args: { start: START, days: DAYS, dayWidth: 24, height: 52, labelRoom: 18, color: 'var(--data-color-1)' },
    parameters: { testOptions: { snapshotBrowsers: [] } },
}
export default meta
type Story = StoryObj<typeof ReleaseRolloutChart>

export const SteppedWithSchedule: Story = {
    args: {
        steps: [step(0, 8, 10), step(8, 15, 25), step(15, 17, 50), step(19, 22, 75, true), step(22, 30, 100, true)],
    },
}

export const DenseHistory: Story = {
    args: {
        steps: Array.from({ length: 15 }, (_, index) => step(index, index + 1, 5 + index * 3)),
        note: '+5 flags',
    },
}
