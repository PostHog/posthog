import { daysUntilCapReached, exhaustionForecast, hasBillableSpend, projectQuota, quotaUx } from './quotaProjection'
import { makeQuota } from './quotaTestUtils'

describe('hasBillableSpend', () => {
    it.each([
        ['null quota keeps the dollars rather than flickering', null, true],
        ['uncapped org is metered', makeQuota({ credit_limit: null, remaining: null }), true],
        [
            'limit is entirely the free allocation',
            makeQuota({ credit_limit: 2_500, free_monthly_credits: 2_500 }),
            false,
        ],
        ['limit exceeds the free allocation', makeQuota({ credit_limit: 7_500, free_monthly_credits: 2_500 }), true],
        ['zero limit cannot bill', makeQuota({ credit_limit: 0, free_monthly_credits: 2_500 }), false],
    ])('%s', (_name, quota, expected) => {
        expect(hasBillableSpend(quota)).toBe(expected)
    })
})

describe('projectQuota', () => {
    it('returns the empty projection when quota is null or uncapped', () => {
        expect(projectQuota(null)).toMatchObject({ status: 'safe', usedPct: 0, projectedPct: 0 })
        expect(projectQuota(makeQuota({ credit_limit: null, remaining: null }))).toMatchObject({
            status: 'safe',
        })
    })

    it('treats a zero limit as fully blocking, not uncapped', () => {
        const proj = projectQuota(makeQuota({ credit_limit: 0, remaining: 0, exhausted: true }))
        expect(proj.status).toBe('danger')
        expect(proj.exhausted).toBe(true)
    })

    it('safe when the fleet rate projects well under the cap', () => {
        // 3,000/month fleet → 100/day → ends at 3,000 of 10,000.
        const proj = projectQuota(makeQuota({ credits_used: 1_000, projected_monthly_credits: 3_000 }))
        expect(proj.status).toBe('safe')
    })

    it('zero fleet rate projects flat usage to period end', () => {
        const proj = projectQuota(makeQuota({ credits_used: 4_000 }))
        expect(proj.projectedPct).toBe(0)
        expect(proj.capReachDate).toBeNull()
    })

    it('warning when the fleet projection crosses the warn threshold but stays under cap', () => {
        // 3,000 used + 9,000/month fleet → 300/day × 20 days → ends at 9,000 (90% of cap).
        const proj = projectQuota(makeQuota({ credits_used: 3_000, projected_monthly_credits: 9_000 }))
        expect(proj.status).toBe('warning')
    })

    it('danger when projected to exhaust before period end', () => {
        // 9,000 used + 100/day → cap reached in 10 days, 20 days left in the period.
        const proj = projectQuota(makeQuota({ credits_used: 9_000, projected_monthly_credits: 3_000 }))
        expect(proj.status).toBe('danger')
        expect(proj.capReachDate).not.toBeNull()
    })

    it('danger when spend has passed the limit even without backend exhaustion', () => {
        // The startup-cap display clamp can lower credit_limit below credits_used while exhausted stays false;
        // that state must not read quieter than merely approaching the limit.
        const proj = projectQuota(makeQuota({ credits_used: 12_000 }))
        expect(proj.status).toBe('danger')
        expect(proj.exhausted).toBe(false)
        expect(proj.usedPct).toBe(120)
    })

    it('danger when explicitly exhausted regardless of the fleet rate', () => {
        const proj = projectQuota(makeQuota({ credits_used: 10_000, remaining: 0, exhausted: true }))
        expect(proj.status).toBe('danger')
        expect(proj.exhausted).toBe(true)
    })

    it('a positive scanner delta raises the projection on top of the fleet sum', () => {
        const base = projectQuota(makeQuota({ credits_used: 1_000, projected_monthly_credits: 3_000 }))
        const withDelta = projectQuota(makeQuota({ credits_used: 1_000, projected_monthly_credits: 3_000 }), 6_000)
        expect(withDelta.projectedPct).toBeGreaterThan(base.projectedPct)
    })

    it('a negative scanner delta lowers the projection and clamps at zero', () => {
        // 2,000/month over a 30-day period × 20 remaining days = ~1,333 of the 10,000 cap.
        const lowered = projectQuota(makeQuota({ projected_monthly_credits: 3_000 }), -1_000)
        expect(lowered.projectedPct).toBeCloseTo(13.33, 1)
        const clamped = projectQuota(makeQuota({ projected_monthly_credits: 3_000 }), -9_000)
        expect(clamped.projectedPct).toBe(0)
    })

    it.each([
        // Cap 10,000 with a 2,500 free allocation.
        ['all spend still inside the free tier', 1_000, 10, 10],
        ['free portion caps at the allocation', 4_000, 40, 25],
        ['nothing spent, nothing free', 0, 0, 0],
    ])('usedFreePct: %s', (_name, creditsUsed, expectedUsedPct, expectedFreePct) => {
        const proj = projectQuota(makeQuota({ credits_used: creditsUsed }))
        expect(proj.usedPct).toBe(expectedUsedPct)
        expect(proj.usedFreePct).toBe(expectedFreePct)
    })

    it('reports unclamped percentages on overshoot', () => {
        // 8,000 used + 30,000/month × 20 days = 20,000 more → 280% of the 10,000 cap.
        const proj = projectQuota(makeQuota({ credits_used: 8_000, projected_monthly_credits: 30_000 }))
        expect(proj.projectedPct).toBeCloseTo(200, 0)
    })
})

describe('daysUntilCapReached', () => {
    it.each([
        // 1,000 left of the 10,000 cap, burned at monthly/30 per day.
        ['inside the window', { credits_used: 9_000, projected_monthly_credits: 15_000 }, 2],
        ['further out than the window', { credits_used: 9_000, projected_monthly_credits: 3_000 }, null],
        ['already exhausted', { credits_used: 9_000, projected_monthly_credits: 15_000, exhausted: true }, null],
        ['no fleet spend, so the cap is never reached', { credits_used: 9_000 }, null],
    ])('%s', (_name, overrides, expected) => {
        const days = daysUntilCapReached(projectQuota(makeQuota(overrides)))
        // Rounded: the two `dayjs()` calls behind the diff are milliseconds apart.
        expect(days === null ? null : Math.round(days * 100) / 100).toBe(expected)
    })
})

describe('quotaUx', () => {
    it('returns nothing when no limit is configured', () => {
        expect(quotaUx(null)).toEqual({})
        // A zero limit with the backend reporting exhaustion must block, not read as uncapped.
        expect(quotaUx(makeQuota({ credit_limit: 0, remaining: 0, exhausted: true })).disabledReason).toMatch(
            /spend limit reached/i
        )
        // Uncapped orgs never block or warn.
        expect(quotaUx(makeQuota({ credit_limit: null, credits_used: 999_999, remaining: null }))).toEqual({})
    })

    it('blocks with a disabledReason when exhausted', () => {
        const ux = quotaUx(makeQuota({ credits_used: 10_000, remaining: 0, exhausted: true }))
        expect(ux.disabledReason).toMatch(/spend limit reached/i)
        expect(ux.tooltip).toBeUndefined()
    })

    it('shows a remaining-credits tooltip near the warn threshold but does not block', () => {
        const ux = quotaUx(makeQuota({ credits_used: 8_500, remaining: 1_500 }))
        expect(ux.disabledReason).toBeUndefined()
        expect(ux.tooltip).toContain('1,500 credits left')
    })

    // A deliberate $0 cap is not a free plan, so it keeps the spend-limit wording.
    it('keeps spend-limit wording for a zero limit', () => {
        const ux = quotaUx(makeQuota({ credit_limit: 0, remaining: 0, exhausted: true }))
        expect(ux.disabledReason).toMatch(/spend limit reached/i)
    })

    it('tells a free-tier org its credits ran out, not that it hit a spend limit', () => {
        const ux = quotaUx(
            makeQuota({
                credit_limit: 2_500,
                free_monthly_credits: 2_500,
                credits_used: 2_500,
                remaining: 0,
                exhausted: true,
            })
        )
        expect(ux.disabledReason).toMatch(/free Replay vision credits/i)
        expect(ux.disabledReason).not.toMatch(/spend limit/i)
    })

    it('returns nothing while usage is well under the threshold', () => {
        expect(quotaUx(makeQuota({ credits_used: 1_000, remaining: 9_000 }))).toEqual({})
    })
})

describe('exhaustionForecast', () => {
    // Frozen 10 days into a July 1-31 period.
    beforeEach(() => {
        jest.useFakeTimers().setSystemTime(new Date('2026-07-11T00:00:00Z'))
    })
    afterEach(() => {
        jest.useRealTimers()
    })

    const PERIOD_START = '2026-07-01T00:00:00Z'
    const PERIOD_END = '2026-07-31T00:00:00Z'

    it.each([
        ['uncapped', 5_000, null],
        ['no spend yet', 0, 10_000],
        ['already at the limit', 10_000, 10_000],
        ['burn too slow to hit the limit this period', 1_000, 10_000],
    ])('returns null when %s', (_name, creditsUsed, creditLimit) => {
        expect(exhaustionForecast(creditsUsed, creditLimit, PERIOD_START, PERIOD_END)).toBeNull()
    })

    it('extrapolates the burn rate to the exhaustion date', () => {
        // 5,000 of 10,000 spent in 10 days: the other half runs out 10 days from now.
        expect(exhaustionForecast(5_000, 10_000, PERIOD_START, PERIOD_END)).toBe('Jul 21')
    })
})
