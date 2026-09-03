import { fleetContributions } from './quotaContributions'
import { makeQuota } from './quotaTestUtils'
import { type SpendVerdictKind, spendVerdict } from './spendVerdict'

describe('spendVerdict', () => {
    // 20 of 30 period days remain, so a monthly rate lands at 2/3 of its value.
    test.each<[string, Parameters<typeof makeQuota>[0] | null, boolean, SpendVerdictKind, string]>([
        [
            'uncapped org',
            { credit_limit: null, remaining: null, scanners_monthly_credits: 3000 },
            false,
            'uncapped',
            'No spend limit',
        ],
        ['low spend and projection', { credits_used: 1000, scanners_monthly_credits: 1500 }, false, 'safe', 'On track'],
        [
            'projection at 85% of the limit',
            { credits_used: 5000, scanners_monthly_credits: 5250 },
            false,
            'warning',
            'Nearing limit',
        ],
        [
            'backend exhausted',
            { credits_used: 10_000, remaining: 0, exhausted: true },
            false,
            'paused',
            'Limit reached',
        ],
        [
            'exhausted on the free plan',
            { credit_limit: 2500, credits_used: 2500, remaining: 0, exhausted: true },
            true,
            'paused',
            'Out of free credits',
        ],
        // The startup cap can clamp the displayed limit below spend while the backend still allows scanning.
        [
            'over the displayed limit, not exhausted',
            { credits_used: 11_000, exhausted: false },
            false,
            'danger',
            'Over limit',
        ],
    ])('%s', (_name, overrides, onFreePlan, expectedKind, expectedPill) => {
        const quota = overrides === null ? null : makeQuota(overrides)
        const verdict = spendVerdict(quota, fleetContributions(quota), { onFreePlan })
        expect(verdict.kind).toBe(expectedKind)
        expect(verdict.pillLabel).toBe(expectedPill)
    })

    // Credits are projected before any percentage is rounded, so headlines move in credits, not in 1% of the limit.
    it.each<[string, Parameters<typeof makeQuota>[0], number]>([
        // 20 of 30 days left: 1,500/30 * 20 = 1,000 on top of spend.
        ['capped, mid-period', { credits_used: 1_234, scanners_monthly_credits: 1_500 }, 2_234],
        ['capped, over the limit', { credits_used: 6_000, scanners_monthly_credits: 12_000 }, 14_000],
        [
            'uncapped',
            { credit_limit: null, remaining: null, credits_used: 400, scanners_monthly_credits: 3_000 },
            2_400,
        ],
        ['with a backfill commitment', { credits_used: 100, backfills_committed_credits: 250 }, 350],
    ])('projects demand in credits: %s', (_name, overrides, expected) => {
        const quota = makeQuota(overrides)
        expect(spendVerdict(quota, fleetContributions(quota), { onFreePlan: false }).projectedDemandCredits).toBe(
            expected
        )
    })

    it('dates the cap from committed one-offs when they alone overshoot it', () => {
        const quota = makeQuota({ credits_used: 5_000, backfills_committed_credits: 6_000 })
        const verdict = spendVerdict(quota, fleetContributions(quota), { onFreePlan: false })
        expect(verdict.kind).toBe('danger')
        expect(verdict.pillLabel).toMatch(/^Limit by /)
    })

    it('pins the bar at 100 while the headline keeps the real overshoot', () => {
        const quota = makeQuota({ credits_used: 6000, scanners_monthly_credits: 12_000 })
        const verdict = spendVerdict(quota, fleetContributions(quota), { onFreePlan: false })
        expect(verdict.kind).toBe('danger')
        expect(verdict.pillLabel).toMatch(/^Limit by /)
        expect(verdict.spentPct + verdict.projectedPct).toBeLessThanOrEqual(100)
        expect(verdict.periodEndPct).toBeGreaterThan(100)
    })
})
