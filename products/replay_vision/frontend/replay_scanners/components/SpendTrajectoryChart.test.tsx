import { render } from '@testing-library/react'

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
    const renderChart = (overrides: Parameters<typeof makeQuota>[0] = {}, spend?: SpendSeries): HTMLElement => {
        const quota = makeQuota(overrides)
        return render(
            <SpendTrajectoryChart
                quota={quota}
                dailyCredits={spend ?? series(quota.credits_used, 5, quota.period_start)}
                projectedTotal={quota.credits_used}
                capReachDate={null}
                statusVar="var(--success)"
            />
        ).container
    }

    // A free allocation this small sits on the axis, where the line reads as the axis and its label
    // lands on the period end date.
    it('hides the free-credits line when it would sit on the axis', () => {
        const container = renderChart({ credit_limit: 240_000, credits_used: 168_000, free_monthly_credits: 1_000 })
        expect(container.textContent).not.toContain('Free credits')
    })

    it('keeps the free-credits line when it clears the axis', () => {
        const container = renderChart({ credit_limit: 10_000, credits_used: 4_000, free_monthly_credits: 2_500 })
        expect(container.textContent).toContain('Free credits')
    })

    // The series and the quota are fetched together, so the series can be a moment newer. Today has to
    // read the same number the card header shows rather than the higher of the two.
    it('reports today at the quota total even when the ledger series runs ahead', () => {
        const quota = makeQuota({ credit_limit: 10_000, credits_used: 4_000 })
        const { container } = render(
            <SpendTrajectoryChart
                quota={quota}
                dailyCredits={series(4_400, 4, quota.period_start)}
                projectedTotal={4_000}
                capReachDate={null}
                statusVar="var(--success)"
            />
        )
        expect(container.textContent).toContain('Today · 4,000')
    })
})
