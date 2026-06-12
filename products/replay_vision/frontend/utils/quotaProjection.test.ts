import { projectQuota, quotaUx, splitProjectedPct } from './quotaProjection'
import { makeQuota } from './quotaTestUtils'

describe('projectQuota', () => {
    it('returns the empty projection when quota is null or unbounded', () => {
        expect(projectQuota(null)).toMatchObject({ status: 'safe', usedPct: 0, projectedPct: 0 })
        expect(projectQuota(makeQuota({ monthly_quota: 0 }))).toMatchObject({ status: 'safe', percentLabel: 0 })
    })

    it('safe when the fleet rate projects well under the cap', () => {
        // 3,000/month fleet → 100/day → ends at 3,000 of 10,000.
        const proj = projectQuota(makeQuota({ usage_this_month: 1_000, projected_monthly_observations: 3_000 }))
        expect(proj.status).toBe('safe')
        expect(proj.percentLabel).toBe(30)
    })

    it('zero fleet rate projects flat usage to period end', () => {
        const proj = projectQuota(makeQuota({ usage_this_month: 4_000 }))
        expect(proj.projectedPct).toBe(0)
        expect(proj.percentLabel).toBe(40)
        expect(proj.capReachDate).toBeNull()
    })

    it('warning when the fleet projection crosses the warn threshold but stays under cap', () => {
        // 3,000 used + 9,000/month fleet → 300/day × 20 days → ends at 9,000 (90% of cap).
        const proj = projectQuota(makeQuota({ usage_this_month: 3_000, projected_monthly_observations: 9_000 }))
        expect(proj.status).toBe('warning')
        expect(proj.percentLabel).toBe(90)
    })

    it('danger when projected to exhaust before period end', () => {
        // 9,000 used + 100/day → cap reached in 10 days, 20 days left in the period.
        const proj = projectQuota(makeQuota({ usage_this_month: 9_000, projected_monthly_observations: 3_000 }))
        expect(proj.status).toBe('danger')
        expect(proj.capReachDate).not.toBeNull()
    })

    it('danger when explicitly exhausted regardless of the fleet rate', () => {
        const proj = projectQuota(makeQuota({ usage_this_month: 10_000, remaining: 0, exhausted: true }))
        expect(proj.status).toBe('danger')
        expect(proj.exhausted).toBe(true)
    })

    it('a positive scanner delta raises the projection on top of the fleet sum', () => {
        const base = projectQuota(makeQuota({ usage_this_month: 1_000, projected_monthly_observations: 3_000 }))
        const withDelta = projectQuota(
            makeQuota({ usage_this_month: 1_000, projected_monthly_observations: 3_000 }),
            6_000
        )
        expect(withDelta.projectedPct).toBeGreaterThan(base.projectedPct)
        expect(withDelta.percentLabel).toBeGreaterThan(base.percentLabel)
    })

    it('a negative scanner delta lowers the projection and clamps at zero', () => {
        // 2,000/month over a 30-day period × 20 remaining days = ~1,333 of the 10,000 cap.
        const lowered = projectQuota(makeQuota({ projected_monthly_observations: 3_000 }), -1_000)
        expect(lowered.projectedPct).toBeCloseTo(13.33, 1)
        const clamped = projectQuota(makeQuota({ projected_monthly_observations: 3_000 }), -9_000)
        expect(clamped.projectedPct).toBe(0)
    })

    it('reports unclamped percentages on overshoot', () => {
        // 8,000 used + 30,000/month × 20 days = 20,000 more → 280% of the 10,000 cap.
        const proj = projectQuota(makeQuota({ usage_this_month: 8_000, projected_monthly_observations: 30_000 }))
        expect(proj.percentLabel).toBe(280)
        expect(proj.projectedPct).toBeCloseTo(200, 0)
    })
})

describe('splitProjectedPct', () => {
    it('apportions by monthly volume', () => {
        expect(splitProjectedPct(30, 100, 200)).toEqual({ thisScannerPct: 10, othersPct: 20 })
    })

    it('gives everything to this scanner when the fleet is empty', () => {
        expect(splitProjectedPct(30, 100, 0)).toEqual({ thisScannerPct: 30, othersPct: 0 })
    })

    it('defaults the share to zero (no division by zero) when both volumes are zero', () => {
        expect(splitProjectedPct(30, 0, 0)).toEqual({ thisScannerPct: 0, othersPct: 30 })
    })
})

describe('quotaUx', () => {
    it('returns nothing when no quota is configured', () => {
        expect(quotaUx(null)).toEqual({})
        expect(quotaUx(makeQuota({ monthly_quota: 0 }))).toEqual({})
    })

    it('blocks with a disabledReason when exhausted', () => {
        const ux = quotaUx(makeQuota({ usage_this_month: 10_000, remaining: 0, exhausted: true }))
        expect(ux.disabledReason).toMatch(/quota reached/i)
        expect(ux.tooltip).toBeUndefined()
    })

    it('shows a tooltip near the warn threshold but does not block', () => {
        const ux = quotaUx(makeQuota({ usage_this_month: 8_500, remaining: 1_500 }))
        expect(ux.disabledReason).toBeUndefined()
        expect(ux.tooltip).toContain('1,500')
    })

    it('returns nothing while usage is well under the threshold', () => {
        expect(quotaUx(makeQuota({ usage_this_month: 1_000, remaining: 9_000 }))).toEqual({})
    })
})
