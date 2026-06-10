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

    it('safe when current burn projects well under the cap', () => {
        const proj = projectQuota(makeQuota({ usage_this_month: 1_000, remaining: 9_000 }))
        expect(proj.status).toBe('safe')
        expect(proj.projectedPeriodEndRatio).toBeLessThan(QUOTA_WARN_THRESHOLD)
    })

    it('warning when projection crosses the warn threshold but stays under cap', () => {
        // 3,000 used over 10 days → 300/day. Projected to end at 9,000 (90% of cap) without exhausting.
        const proj = projectQuota(makeQuota({ usage_this_month: 3_000, remaining: 7_000 }))
        expect(proj.status).toBe('warning')
        expect(proj.projectedPeriodEndRatio).toBeGreaterThanOrEqual(QUOTA_WARN_THRESHOLD)
        expect(proj.capReachInPeriod).toBe(false)
    })

    it('danger when projected to exhaust before period end', () => {
        const proj = projectQuota(makeQuota({ usage_this_month: 9_000, remaining: 1_000 }))
        expect(proj.status).toBe('danger')
        expect(proj.capReachInPeriod).toBe(true)
        expect(proj.capReachDate).not.toBeNull()
    })

    it('danger when explicitly exhausted regardless of historical burn', () => {
        const proj = projectQuota(makeQuota({ usage_this_month: 10_000, remaining: 0, exhausted: true }))
        expect(proj.status).toBe('danger')
    })

    it('projection is unconfident before 3 days have elapsed', () => {
        const now = dayjs()
        const proj = projectQuota(
            makeQuota({
                period_start: now.subtract(1, 'day').toISOString(),
                period_end: now.add(29, 'day').toISOString(),
            })
        )
        expect(proj.projectionConfident).toBe(false)
    })

    it('adds scanner projected monthly on top of historical burn', () => {
        const noScanner = projectQuota(makeQuota({ usage_this_month: 1_000, remaining: 9_000 }))
        const withScanner = projectQuota(makeQuota({ usage_this_month: 1_000, remaining: 9_000 }), 6_000)
        expect(withScanner.combinedDailyRate).toBeGreaterThan(noScanner.combinedDailyRate)
        expect(withScanner.projectedPeriodEndRatio).toBeGreaterThan(noScanner.projectedPeriodEndRatio)
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
