import { render } from '@testing-library/react'

import { getHogChart, setupJsdom, setupSyncRaf } from '@posthog/quill-charts/testing'

import { dayjs } from 'lib/dayjs'

import { makeQuota } from '../../utils/quotaTestUtils'
import type { SpendSeries } from '../visionUsageLogic'
import { SpendTrajectoryChart } from './SpendTrajectoryChart'

/** Daily spend over the fixture's period, oldest first, splitting `total` evenly across `days`. */
function series(total: number, days: number, periodStart: string): SpendSeries {
    const start = dayjs.utc(periodStart)
    return Array.from({ length: days }, (_, i) => ({
        date: start.add(i, 'day').format('YYYY-MM-DD'),
        credits: Math.round(total / days),
    }))
}

describe('SpendTrajectoryChart', () => {
    let cleanupJsdom: () => void
    let cleanupRaf: () => void
    beforeEach(() => {
        cleanupJsdom = setupJsdom()
        cleanupRaf = setupSyncRaf()
    })
    afterEach(() => {
        cleanupRaf()
        cleanupJsdom()
    })

    it('draws captioned limit and free-credit lines and labels today at the quota total', () => {
        const quota = makeQuota({ credit_limit: 10_000, credits_used: 4_000, free_monthly_credits: 2_500 })
        const { container } = render(
            <SpendTrajectoryChart
                quota={quota}
                dailyCredits={series(4_000, 5, quota.period_start)}
                projectedTotal={4_000}
                capReachDate={null}
                statusVar="var(--success)"
            />
        )
        const chart = getHogChart(container)
        expect(chart.referenceLines().map((line) => line.label)).toEqual([null, null])
        expect(container.querySelector('[data-attr="hog-chart-reference-line-hit-area"]')).toBeNull()
        expect(container.querySelector('[data-attr="spend-trajectory-reference-label-limit"]')?.textContent).toBe(
            'Monthly limit · 10,000'
        )
        expect(container.querySelector('[data-attr="spend-trajectory-reference-label-free"]')?.textContent).toBe(
            'Free credits · 2,500'
        )
        expect(container.querySelector('[data-attr="spend-trajectory-marker-today"]')?.textContent).toBe(
            'Today · 4,000'
        )
    })
})
