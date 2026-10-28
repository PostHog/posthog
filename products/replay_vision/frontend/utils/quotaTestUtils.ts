import type { VisionQuotaApi } from '../generated/api.schemas'

/** Test-only `VisionQuotaApi` builder: a 10,000 cap with 20 of 30 period days remaining. */
export function makeQuota(overrides: Partial<VisionQuotaApi> = {}): VisionQuotaApi {
    const now = new Date()
    const daysFromNow = (days: number): string => new Date(now.getTime() + days * 24 * 3600 * 1000).toISOString()
    const quota: VisionQuotaApi = {
        credit_limit: 10_000,
        credits_used: 0,
        credits_settled: 0,
        credits_reserved: 0,
        remaining: 10_000,
        exhausted: false,
        projected_monthly_credits: 0,
        scanners_monthly_credits: 0,
        backfills_committed_credits: 0,
        free_monthly_credits: 2500,
        period_start: daysFromNow(-10),
        period_end: daysFromNow(20),
        scanners_period_credits: 0,
        ...overrides,
    }
    // The backend pro-rates the rate to the 20 days left; keep the fixture consistent unless a test overrides it.
    return 'scanners_period_credits' in overrides
        ? quota
        : { ...quota, scanners_period_credits: (quota.scanners_monthly_credits * 20) / 30 }
}
