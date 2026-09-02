import type { VisionQuotaApi } from '../generated/api.schemas'
import { type QuotaContribution, buildQuotaMeter } from './quotaContributions'

const HALF_PERIOD_QUOTA: VisionQuotaApi = {
    credit_limit: 1000,
    credits_used: 100,
    remaining: 900,
    exhausted: false,
    free_monthly_credits: 0,
    projected_monthly_credits: 400,
    scanners_monthly_credits: 400,
    backfills_committed_credits: 0,
    // Half the period is left, so a monthly rate lands at half value and a one-off lands whole.
    period_start: '2026-05-01T00:00:00Z',
    period_end: '2026-05-03T00:00:00Z',
} as VisionQuotaApi

const contribution = (overrides: Partial<QuotaContribution>): QuotaContribution => ({
    key: 'k',
    label: 'l',
    credits: 0,
    kind: 'monthly-rate',
    barClass: 'bg-accent',
    ...overrides,
})

describe('quotaContributions', () => {
    beforeEach(() => {
        jest.useFakeTimers().setSystemTime(new Date('2026-05-02T00:00:00Z'))
    })
    afterEach(() => {
        jest.useRealTimers()
    })

    it('charges a one-off in full while pro-rating a rate over the days left', () => {
        // The bug this prevents: routing a backfill through the rate path shrank it to a fraction.
        const { segments } = buildQuotaMeter(HALF_PERIOD_QUOTA, [
            contribution({ key: 'backfill', credits: 200, kind: 'one-off' }),
            contribution({ key: 'scanners', credits: 200, kind: 'monthly-rate' }),
        ])
        const bySegment = Object.fromEntries(segments.map((s) => [s.key, s.pct]))
        expect(bySegment.backfill).toBeCloseTo(20)
        expect(bySegment.scanners).toBeCloseTo(10)
    })

    it('splits one projection across rate contributions instead of pro-rating each separately', () => {
        const { projection, segments } = buildQuotaMeter(HALF_PERIOD_QUOTA, [
            contribution({ key: 'others', credits: 300 }),
            contribution({ key: 'mine', credits: 100 }),
        ])
        const total = segments.reduce((sum, s) => sum + s.pct, 0)
        expect(total).toBeCloseTo(projection.projectedPct)
        expect(segments[0].pct).toBeCloseTo(segments[1].pct * 3)
    })

    it('keeps the headline percentage equal to what the bar draws', () => {
        // The other bug: a headline computed apart from the segments disagreed with them.
        const model = buildQuotaMeter(HALF_PERIOD_QUOTA, [
            contribution({ key: 'backfill', credits: 350, kind: 'one-off' }),
            contribution({ key: 'scanners', credits: 400 }),
        ])
        const drawn = model.projection.usedPct + model.segments.reduce((sum, s) => sum + s.pct, 0)
        expect(model.periodEndPct).toBe(Math.round(drawn))
    })

    it('reports no cap and zero-width segments for an uncapped org', () => {
        const model = buildQuotaMeter({ ...HALF_PERIOD_QUOTA, credit_limit: null } as VisionQuotaApi, [
            contribution({ key: 'backfill', credits: 500, kind: 'one-off' }),
        ])
        expect(model.hasCap).toBe(false)
        expect(model.segments[0].pct).toBe(0)
    })
})
