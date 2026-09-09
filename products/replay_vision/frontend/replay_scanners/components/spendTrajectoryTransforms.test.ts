import { dayjs } from 'lib/dayjs'

import { makeQuota } from '../../utils/quotaTestUtils'
import type { SpendSeries } from '../visionUsageLogic'
import { PROJECTED_SERIES_KEY, SPENT_SERIES_KEY, buildSpendTrajectory } from './spendTrajectoryTransforms'

const PERIOD = { period_start: '2026-05-01T00:00:00Z', period_end: '2026-06-01T00:00:00Z' }
const NOW = dayjs.utc('2026-05-12T10:00:00Z')
const TODAY_INDEX = 11
const END_INDEX = 31
const STATUS = 'var(--success)'
const DANGER = 'var(--danger)'

function ledger(total: number, days: number): SpendSeries {
    return Array.from({ length: days }, (_, i) => ({
        date: dayjs.utc(PERIOD.period_start).add(i, 'day').format('YYYY-MM-DD'),
        credits: Math.round(total / days),
    }))
}

function build(
    overrides: Parameters<typeof makeQuota>[0],
    extra: { dailyCredits?: SpendSeries; projectedTotal?: number; capReachDate?: dayjs.Dayjs | null } = {}
): ReturnType<typeof buildSpendTrajectory> {
    const quota = makeQuota({ ...PERIOD, ...overrides })
    return buildSpendTrajectory({
        quota,
        dailyCredits: extra.dailyCredits ?? ledger(quota.credits_used, TODAY_INDEX + 1),
        projectedTotal: extra.projectedTotal ?? quota.credits_used,
        capReachDate: extra.capReachDate ?? null,
        statusColor: STATUS,
        dangerColor: DANGER,
        now: NOW,
    })
}

function seriesData(trajectory: ReturnType<typeof buildSpendTrajectory>, key: string): number[] {
    return trajectory.series.find((s) => s.key === key)!.data as number[]
}

describe('buildSpendTrajectory', () => {
    it('lays one UTC day per label across the period and stops the spent line at today', () => {
        const trajectory = build({ credits_used: 4_000 })
        expect(trajectory.labels).toHaveLength(END_INDEX + 1)
        expect(trajectory.labels[0]).toBe('2026-05-01')
        expect(trajectory.labels[END_INDEX]).toBe('2026-06-01')
        const spent = seriesData(trajectory, SPENT_SERIES_KEY)
        expect(spent[TODAY_INDEX]).toBe(4_000)
        expect(spent[TODAY_INDEX + 1]).toBeNaN()
    })

    // The series and the quota are fetched together, so the series can be a moment newer. Today has to
    // read the same number the card header shows, and only the days that overshoot it are pulled down.
    it('pins today to the quota total when the ledger runs ahead', () => {
        const trajectory = build({ credits_used: 4_000 }, { dailyCredits: ledger(4_400, 4) })
        const spent = seriesData(trajectory, SPENT_SERIES_KEY)
        expect(spent[2]).toBe(3_300)
        expect(spent[3]).toBe(4_000)
        expect(spent[TODAY_INDEX]).toBe(4_000)
        expect(trajectory.markers.find((m) => m.key === 'today')?.text).toBe('Today · 4,000')
    })

    it.each([
        [
            'it would sit on the axis',
            { credit_limit: 240_000, credits_used: 168_000, free_monthly_credits: 1_000 },
            null,
        ],
        [
            'it clears the axis and the limit',
            { credit_limit: 10_000, credits_used: 4_000, free_monthly_credits: 2_500 },
            2_500,
        ],
        ['it is the limit itself', { credit_limit: 2_500, credits_used: 1_000, free_monthly_credits: 2_500 }, null],
    ])('draws the free-credits line only when %s', (_, overrides, expected) => {
        expect(build(overrides).freeCredits).toBe(expected)
    })

    it('runs the projection to the crossing in the danger colour when demand hits the limit', () => {
        const trajectory = build(
            { credit_limit: 10_000, credits_used: 4_000 },
            { projectedTotal: 10_000, capReachDate: dayjs.utc('2026-05-20T06:00:00Z') }
        )
        const projected = seriesData(trajectory, PROJECTED_SERIES_KEY)
        expect(projected[TODAY_INDEX]).toBe(4_000)
        expect(projected[20]).toBe(10_000)
        expect(projected[21]).toBeNaN()
        expect(trajectory.series.find((s) => s.key === PROJECTED_SERIES_KEY)?.color).toBe(DANGER)
        expect(trajectory.markers.find((m) => m.key === 'crossing')).toMatchObject({
            label: '2026-05-21',
            value: 10_000,
            text: 'Limit · May 20',
        })
        expect(trajectory.crossingDate?.format('YYYY-MM-DD')).toBe('2026-05-20')
    })

    it('runs the projection to demand at period end when there is no limit', () => {
        const trajectory = build({ credit_limit: null, credits_used: 4_000 }, { projectedTotal: 6_000 })
        const projected = seriesData(trajectory, PROJECTED_SERIES_KEY)
        expect(trajectory.cap).toBeNull()
        expect(projected[END_INDEX]).toBe(6_000)
        expect(trajectory.series.find((s) => s.key === PROJECTED_SERIES_KEY)?.color).toBe(STATUS)
        expect(trajectory.markers.find((m) => m.key === 'end')?.text).toBe('Jun 1 · ~6,000')
    })

    it('holds the projection flat at the limit once spend has reached it', () => {
        const trajectory = build({ credit_limit: 10_000, credits_used: 10_000 }, { projectedTotal: 14_000 })
        const projected = seriesData(trajectory, PROJECTED_SERIES_KEY)
        expect(trajectory.pausedAtLimit).toBe(true)
        expect(projected[TODAY_INDEX]).toBe(10_000)
        expect(projected[END_INDEX]).toBe(10_000)
        expect(trajectory.series.find((s) => s.key === PROJECTED_SERIES_KEY)?.color).toBe(DANGER)
    })
})
