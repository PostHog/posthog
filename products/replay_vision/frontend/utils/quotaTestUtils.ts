import type { VisionQuotaApi } from '../generated/api.schemas'

/** Test-only `VisionQuotaApi` builder: a 10,000 cap with 20 of 30 period days remaining. */
export function makeQuota(overrides: Partial<VisionQuotaApi> = {}): VisionQuotaApi {
    const now = new Date()
    const daysFromNow = (days: number): string => new Date(now.getTime() + days * 24 * 3600 * 1000).toISOString()
    return {
        monthly_quota: 10_000,
        usage_this_month: 0,
        remaining: 10_000,
        exhausted: false,
        projected_monthly_observations: 0,
        period_start: daysFromNow(-10),
        period_end: daysFromNow(20),
        ...overrides,
    }
}
