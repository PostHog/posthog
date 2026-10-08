import { cleanup, render, screen } from '@testing-library/react'
import type { ComponentProps } from 'react'

import { type HogChart, ensureJsdom, getHogChart } from '@posthog/quill-charts/testing'

import { dayjs } from 'lib/dayjs'

import { makeQuota } from '../../utils/quotaTestUtils'
import type { SpendSeries } from '../visionUsageLogic'
import { SpendTrajectoryChart } from './SpendTrajectoryChart'

type Props = ComponentProps<typeof SpendTrajectoryChart>

function series(total: number, days: number, periodStart: string): SpendSeries {
    const start = dayjs.utc(periodStart)
    return Array.from({ length: days }, (_, i) => ({
        date: start.add(i, 'day').format('YYYY-MM-DD'),
        credits: Math.round(total / days),
    }))
}

function renderChart(overrides: Partial<Props> = {}): HogChart {
    const quota = makeQuota({ credit_limit: 10_000, credits_used: 4_000, free_monthly_credits: 2_500 })
    const { container } = render(
        <SpendTrajectoryChart
            quota={quota}
            dailyCredits={series(4_000, 5, quota.period_start)}
            projectedTotal={4_000}
            capReachDate={null}
            statusVar="var(--success)"
            {...overrides}
        />
    )
    return getHogChart(container)
}

describe('SpendTrajectoryChart', () => {
    beforeEach(() => ensureJsdom())
    afterEach(() => cleanup())

    it('draws captioned limit and free-credit lines and labels today at the quota total', () => {
        const chart = renderChart()
        const [limit, free] = chart.referenceLines()
        expect(chart.referenceLines().map((line) => line.label)).toEqual([null, null])
        expect(limit.position).not.toBeNull()
        expect(free.position).not.toBeNull()
        expect(limit.position!).toBeLessThan(free.position!)
        expect(document.querySelector('[data-attr="hog-chart-reference-line-hit-area"]')).toBeNull()
        expect(screen.getByText('Monthly limit · 10,000')).toBeTruthy()
        expect(screen.getByText('Free credits · 2,500')).toBeTruthy()
        expect(screen.getByText('Today · 4,000')).toBeTruthy()
    })
})
