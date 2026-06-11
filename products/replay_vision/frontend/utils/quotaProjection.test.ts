import { dayjs } from 'lib/dayjs'

import type { VisionQuotaApi } from '../generated/api.schemas'
import { QUOTA_WARN_THRESHOLD, projectQuota, quotaUx } from './quotaProjection'

function makeQuota(overrides: Partial<VisionQuotaApi> = {}): VisionQuotaApi {
    const now = dayjs()
    return {
        monthly_quota: 10_000,
        usage_this_month: 0,
        remaining: 10_000,
        exhausted: false,
        projected_monthly_observations: 0,
        period_start: now.subtract(10, 'day').toISOString(),
        period_end: now.add(20, 'day').toISOString(),
        ...overrides,
    } as VisionQuotaApi
}

describe('projectQuota', () => {
    it('returns the empty projection when quota is null or unbounded', () => {
        expect(projectQuota(null)).toMatchObject({ status: 'safe', daysRemaining: 0 })
        expect(projectQuota(makeQuota({ monthly_quota: 0 }))).toMatchObject({ status: 'safe', combinedDailyRate: 0 })
    })

    it('safe when the fleet rate projects well under the cap', () => {
        // 3,000/month fleet → 100/day → ends at 3,000 of 10,000.
        const proj = projectQuota(makeQuota({ usage_this_month: 1_000, projected_monthly_observations: 3_000 }))
        expect(proj.status).toBe('safe')
        expect(proj.projectedPeriodEndRatio).toBeLessThan(QUOTA_WARN_THRESHOLD)
    })

    it('zero fleet rate projects flat usage to period end', () => {
        const proj = projectQuota(makeQuota({ usage_this_month: 4_000 }))
        expect(proj.combinedDailyRate).toBe(0)
        expect(proj.projectedPeriodEndRatio).toBeCloseTo(0.4)
        expect(proj.capReachDate).toBeNull()
    })

    it('warning when the fleet projection crosses the warn threshold but stays under cap', () => {
        // 3,000 used + 9,000/month fleet → 300/day × 20 days → ends at 9,000 (90% of cap).
        const proj = projectQuota(makeQuota({ usage_this_month: 3_000, projected_monthly_observations: 9_000 }))
        expect(proj.status).toBe('warning')
        expect(proj.projectedPeriodEndRatio).toBeGreaterThanOrEqual(QUOTA_WARN_THRESHOLD)
        expect(proj.capReachInPeriod).toBe(false)
    })

    it('danger when projected to exhaust before period end', () => {
        // 9,000 used + 100/day → cap reached in 10 days, 20 days left in the period.
        const proj = projectQuota(makeQuota({ usage_this_month: 9_000, projected_monthly_observations: 3_000 }))
        expect(proj.status).toBe('danger')
        expect(proj.capReachInPeriod).toBe(true)
        expect(proj.capReachDate).not.toBeNull()
    })

    it('danger when explicitly exhausted regardless of the fleet rate', () => {
        const proj = projectQuota(makeQuota({ usage_this_month: 10_000, remaining: 0, exhausted: true }))
        expect(proj.status).toBe('danger')
    })

    it('a positive scanner delta raises the projection on top of the fleet sum', () => {
        const base = projectQuota(makeQuota({ usage_this_month: 1_000, projected_monthly_observations: 3_000 }))
        const withDelta = projectQuota(
            makeQuota({ usage_this_month: 1_000, projected_monthly_observations: 3_000 }),
            6_000
        )
        expect(withDelta.combinedDailyRate).toBeGreaterThan(base.combinedDailyRate)
        expect(withDelta.projectedPeriodEndRatio).toBeGreaterThan(base.projectedPeriodEndRatio)
    })

    it('a negative scanner delta lowers the projection and clamps at zero', () => {
        const lowered = projectQuota(makeQuota({ projected_monthly_observations: 3_000 }), -1_000)
        expect(lowered.combinedDailyRate).toBeCloseTo(2_000 / 30)
        const clamped = projectQuota(makeQuota({ projected_monthly_observations: 3_000 }), -9_000)
        expect(clamped.combinedDailyRate).toBe(0)
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
