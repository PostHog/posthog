import { Meta, StoryObj } from '@storybook/react'

import { dayjs } from 'lib/dayjs'

import { LogsAlertSimulateBucketApi, LogsAlertSimulateResponseApi } from 'products/logs/frontend/generated/api.schemas'

import { LogsAlertSimulationChart } from './LogsAlertSimulation'

const THRESHOLD = 40

/** Counts that stay quiet, spike over the threshold for a stretch, then settle back down. */
const COUNTS = [
    8, 12, 6, 14, 9, 11, 7, 13, 10, 18, 24, 46, 71, 88, 64, 52, 43, 39, 22, 15, 11, 9, 14, 8, 12, 7, 10, 13, 6, 11,
]

function buildResult(counts: number[]): LogsAlertSimulateResponseApi {
    const start = dayjs('2026-03-16T09:00:00Z')
    let firing = false
    let fireCount = 0
    let resolveCount = 0

    const buckets: LogsAlertSimulateBucketApi[] = counts.map((count, index) => {
        const breached = count > THRESHOLD
        let notification = 'none'
        if (breached && !firing) {
            notification = 'fire'
            fireCount += 1
            firing = true
        } else if (!breached && firing) {
            notification = 'resolve'
            resolveCount += 1
            firing = false
        }
        return {
            timestamp: start.add(index * 5, 'minute').toISOString(),
            count,
            threshold_breached: breached,
            state: firing ? 'firing' : 'ok',
            notification,
            reason: breached ? 'Count above threshold' : 'Count below threshold',
        }
    })

    return {
        buckets,
        fire_count: fireCount,
        resolve_count: resolveCount,
        total_buckets: buckets.length,
        threshold_count: THRESHOLD,
        threshold_operator: 'above',
    }
}

const meta: Meta<typeof LogsAlertSimulationChart> = {
    title: 'Products/Logs/LogsAlertSimulationChart',
    component: LogsAlertSimulationChart,
    tags: ['autodocs'],
}
export default meta

type Story = StoryObj<typeof LogsAlertSimulationChart>

export const WithBreaches: Story = {
    args: { result: buildResult(COUNTS) },
}

export const NeverBreaches: Story = {
    args: { result: buildResult(COUNTS.map((count) => Math.round(count / 4))) },
}
