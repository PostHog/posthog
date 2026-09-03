import { dayjs } from 'lib/dayjs'

import type { VisionQuotaApi, VisionSpendSeriesApi } from '../generated/api.schemas'

/**
 * Dev-only fake states for every spend surface, driven by `?vision_quota_scenario=<key>`.
 * Lets the quota card, landing page, and usage tab render each state of the spend UI with
 * realistic data, without contorting billing or burning credits. Never active in production
 * builds; the overrides are display-only and the backend still enforces the real quota.
 */

export interface QuotaScenario {
    key: string
    quota: VisionQuotaApi | null
    /** Per-scanner rows for the usage tab; null keeps the real rows. */
    usageScanners: FakeUsageScanner[] | null
    /** Settled credits per UTC day from the period start to today; null keeps the real series request. */
    dailySpend: VisionSpendSeriesApi
}

export interface FakeUsageScanner {
    id: string
    name: string
    enabled: boolean
    credits_this_month: number
    observations_this_month: number
    credits_per_observation: number
    sampling_rate: number
    estimated_monthly_credits: number | null
    estimated_at: string | null
    model: string
}

const SCENARIO_PARAM = 'vision_quota_scenario'

// Hoisted so the production bundle keeps no live path into the fixtures below.
const SCENARIOS_ENABLED = process.env.NODE_ENV !== 'production'

// Scenarios run 18 days into a 30-day period, so the chart has a real spend history to draw
// regardless of today's date.
const SCENARIO_DAYS_ELAPSED = 18

function buildQuota(overrides: Partial<VisionQuotaApi>): VisionQuotaApi {
    const periodStart = dayjs.utc().subtract(SCENARIO_DAYS_ELAPSED, 'day').startOf('day')
    const base = {
        credit_limit: 5000,
        credits_used: 1850,
        remaining: 3150,
        exhausted: false,
        period_start: periodStart.toISOString(),
        period_end: periodStart.add(30, 'day').toISOString(),
        projected_monthly_credits: 2400,
        scanners_monthly_credits: 2100,
        backfills_committed_credits: 300,
        free_monthly_credits: 500,
        credits_settled: 1850,
        credits_reserved: 0,
    }
    return { ...base, ...overrides } as VisionQuotaApi
}

const FAKE_SCANNERS: FakeUsageScanner[] = [
    {
        id: 'scenario-checkout',
        name: 'Checkout errors',
        enabled: true,
        credits_this_month: 820,
        observations_this_month: 410,
        credits_per_observation: 2,
        sampling_rate: 0.25,
        estimated_monthly_credits: 700,
        estimated_at: '2026-01-01T00:00:00Z',
        model: 'standard',
    },
    {
        id: 'scenario-rage',
        name: 'Rage click detector',
        enabled: true,
        credits_this_month: 520,
        observations_this_month: 260,
        credits_per_observation: 2,
        sampling_rate: 0.1,
        estimated_monthly_credits: 900,
        estimated_at: '2026-01-01T00:00:00Z',
        model: 'standard',
    },
    {
        id: 'scenario-signup',
        name: 'Signup friction',
        enabled: true,
        credits_this_month: 510,
        observations_this_month: 255,
        credits_per_observation: 2,
        sampling_rate: 0.05,
        estimated_monthly_credits: 500,
        estimated_at: null,
        model: 'standard',
    },
]

/** Scale a scanner's period spend and monthly estimate together, so the table sums match the quota's fleet rate. */
function scaleScanners(spendFactor: number, estimateFactor: number): FakeUsageScanner[] {
    return FAKE_SCANNERS.map((s) => ({
        ...s,
        credits_this_month: Math.round(s.credits_this_month * spendFactor),
        estimated_monthly_credits:
            s.estimated_monthly_credits === null ? null : Math.round(s.estimated_monthly_credits * estimateFactor),
    }))
}

/**
 * A believable daily burn landing on `total`: gently accelerating, dipping on weekends, with
 * deterministic noise (sine-based, so every render draws the same series).
 */
function rampSpend(total: number): VisionSpendSeriesApi {
    const days = SCENARIO_DAYS_ELAPSED
    const start = dayjs.utc().subtract(SCENARIO_DAYS_ELAPSED, 'day').startOf('day')
    const weights = Array.from({ length: days }, (_, i) => {
        const weekday = start.add(i, 'day').day()
        const weekendDip = weekday === 0 || weekday === 6 ? 0.45 : 1
        const growth = 1 + (1.2 * i) / Math.max(days - 1, 1)
        const noise = 1 + 0.35 * Math.sin(i * 12.9898) * Math.sin(i * 78.233)
        return weekendDip * growth * Math.max(noise, 0.2)
    })
    const weightTotal = weights.reduce((sum, w) => sum + w, 0)
    const daily = weights.map((w) => Math.round((total * w) / weightTotal))
    // Per-day rounding drifts off `total`; settle the difference on the last day so the sum is exact.
    daily[daily.length - 1] += total - daily.reduce((sum, v) => sum + v, 0)
    return {
        period_start: start.toISOString(),
        period_end: start.add(30, 'day').toISOString(),
        days: daily.map((credits, i) => ({ date: start.add(i, 'day').format('YYYY-MM-DD'), credits })),
    }
}

const SCENARIOS: Record<string, () => Omit<QuotaScenario, 'key'>> = {
    'on-track': () => ({
        quota: buildQuota({}),
        usageScanners: FAKE_SCANNERS,
        dailySpend: rampSpend(1850),
    }),
    'nearing-limit': () => ({
        quota: buildQuota({
            credits_used: 2600,
            remaining: 2400,
            projected_monthly_credits: 4400,
            scanners_monthly_credits: 4100,
        }),
        usageScanners: scaleScanners(1.4, 4100 / 2100),
        dailySpend: rampSpend(2600),
    }),
    'limit-soon': () => ({
        quota: buildQuota({
            credits_used: 3900,
            remaining: 1100,
            projected_monthly_credits: 7800,
            scanners_monthly_credits: 7500,
        }),
        usageScanners: scaleScanners(2.1, 7500 / 2100),
        dailySpend: rampSpend(3900),
    }),
    paused: () => ({
        quota: buildQuota({ credits_used: 5000, remaining: 0, exhausted: true }),
        usageScanners: scaleScanners(2.7, 7500 / 2100),
        dailySpend: rampSpend(5000),
    }),
    'free-plan': () => ({
        quota: buildQuota({
            credit_limit: 500,
            credits_used: 260,
            remaining: 240,
            projected_monthly_credits: 420,
            scanners_monthly_credits: 420,
            backfills_committed_credits: 0,
            free_monthly_credits: 500,
        }),
        usageScanners: scaleScanners(1 / 7, 420 / 2100),
        dailySpend: rampSpend(260),
    }),
    'free-paused': () => ({
        quota: buildQuota({
            credit_limit: 500,
            credits_used: 500,
            remaining: 0,
            exhausted: true,
            free_monthly_credits: 500,
        }),
        usageScanners: scaleScanners(1 / 4, 420 / 2100),
        dailySpend: rampSpend(500),
    }),
    'zero-limit': () => ({
        quota: buildQuota({
            credit_limit: 0,
            credits_used: 0,
            remaining: 0,
            exhausted: true,
            projected_monthly_credits: 0,
            scanners_monthly_credits: 0,
            backfills_committed_credits: 0,
        }),
        usageScanners: FAKE_SCANNERS.map((s) => ({ ...s, credits_this_month: 0, observations_this_month: 0 })),
        dailySpend: rampSpend(0),
    }),
    // Large-limit org: a tiny free tier against a big cap, the case that crowded the axis.
    'big-limit': () => ({
        quota: buildQuota({
            credit_limit: 500_000,
            credits_used: 408_560,
            remaining: 91_440,
            projected_monthly_credits: 548_640,
            scanners_monthly_credits: 548_640,
            backfills_committed_credits: 0,
            free_monthly_credits: 2_500,
            credits_settled: 408_560,
            credits_reserved: 0,
        }),
        usageScanners: scaleScanners(140, 140),
        dailySpend: rampSpend(408_560),
    }),
    'no-limit': () => ({
        quota: buildQuota({ credit_limit: null, remaining: null }),
        usageScanners: FAKE_SCANNERS,
        dailySpend: rampSpend(1850),
    }),
    empty: () => ({
        quota: buildQuota({
            credits_used: 0,
            remaining: 5000,
            projected_monthly_credits: 0,
            scanners_monthly_credits: 0,
            backfills_committed_credits: 0,
        }),
        usageScanners: [],
        dailySpend: rampSpend(0),
    }),
}

function scenarioParam(name: string): string | null {
    try {
        return new URLSearchParams(window.location.search).get(name)
    } catch {
        return null
    }
}

/** The active scenario, or null when none is requested (the normal case, and always in production). */
export function currentQuotaScenario(): QuotaScenario | null {
    if (!SCENARIOS_ENABLED) {
        return null
    }
    const key = scenarioParam(SCENARIO_PARAM)
    const build = key && Object.hasOwn(SCENARIOS, key) ? SCENARIOS[key] : null
    if (!key || !build) {
        return null
    }
    return { key, ...build() }
}
