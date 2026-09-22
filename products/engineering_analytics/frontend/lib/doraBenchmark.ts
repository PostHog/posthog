// DORA report performance bands for the four deploy metrics, so each Health tile can say
// which band the current window lands in. Thresholds are loosely modeled on the DORA State
// of DevOps report ladders (elite / high / medium / low), not a literal reproduction: the
// deployment-frequency and change-failure-rate bands are tuned tighter than the published
// report. Our change-failure and recovery figures are also deploy-status proxies, so the
// tile tooltips carry that caveat alongside the ladder.

const DAY_SECONDS = 86400
const WEEK_SECONDS = 7 * DAY_SECONDS
const MONTH_SECONDS = 30 * DAY_SECONDS

export type DoraBand = 'elite' | 'high' | 'medium' | 'low'

export interface DoraBenchmark {
    band: DoraBand
    /** The band name, shown in the label tooltip. */
    label: string
    /** The full DORA ladder for the metric, shown in the label tooltip. */
    tooltip: string
}

const BAND_LABELS: Record<DoraBand, string> = {
    elite: 'Elite',
    high: 'High',
    medium: 'Medium',
    low: 'Low',
}

function benchmark(band: DoraBand, ladder: string): DoraBenchmark {
    return { band, label: BAND_LABELS[band], tooltip: ladder }
}

const FREQUENCY_LADDER =
    'DORA deployment frequency bands: elite deploys on demand (at least daily), high at least weekly, medium at least monthly, low less often.'

export function deploymentFrequencyBenchmark(perDay: number | null | undefined): DoraBenchmark | null {
    if (perDay == null || perDay <= 0) {
        return null
    }
    if (perDay >= 1) {
        return benchmark('elite', FREQUENCY_LADDER)
    }
    if (perDay >= 1 / 7) {
        return benchmark('high', FREQUENCY_LADDER)
    }
    if (perDay >= 1 / 30) {
        return benchmark('medium', FREQUENCY_LADDER)
    }
    return benchmark('low', FREQUENCY_LADDER)
}

const LEAD_TIME_LADDER =
    'DORA lead time bands: elite under a day, high under a week, medium under a month, low over a month. Measured here as PR open to first successful deploy, a close proxy for DORA’s commit to production.'

export function leadTimeBenchmark(seconds: number | null | undefined): DoraBenchmark | null {
    if (seconds == null) {
        return null
    }
    if (seconds < DAY_SECONDS) {
        return benchmark('elite', LEAD_TIME_LADDER)
    }
    if (seconds < WEEK_SECONDS) {
        return benchmark('high', LEAD_TIME_LADDER)
    }
    if (seconds < MONTH_SECONDS) {
        return benchmark('medium', LEAD_TIME_LADDER)
    }
    return benchmark('low', LEAD_TIME_LADDER)
}

const CHANGE_FAILURE_LADDER =
    'DORA change failure rate bands: elite 5% or less, high 10% or less, medium 15% or less, low above 15%. Measured here as the failed deployment share, a proxy with no incident data linked.'

export function changeFailureBenchmark(share: number | null | undefined): DoraBenchmark | null {
    if (share == null) {
        return null
    }
    if (share <= 0.05) {
        return benchmark('elite', CHANGE_FAILURE_LADDER)
    }
    if (share <= 0.1) {
        return benchmark('high', CHANGE_FAILURE_LADDER)
    }
    if (share <= 0.15) {
        return benchmark('medium', CHANGE_FAILURE_LADDER)
    }
    return benchmark('low', CHANGE_FAILURE_LADDER)
}

const RESTORE_LADDER =
    'DORA failed deployment recovery bands: elite under an hour, high under a day, medium under a week, low over a week. Measured here as first failure to the next successful deploy, a proxy that misses non-deploy recoveries.'

export function restoreTimeBenchmark(seconds: number | null | undefined): DoraBenchmark | null {
    if (seconds == null) {
        return null
    }
    if (seconds < 3600) {
        return benchmark('elite', RESTORE_LADDER)
    }
    if (seconds < DAY_SECONDS) {
        return benchmark('high', RESTORE_LADDER)
    }
    if (seconds < WEEK_SECONDS) {
        return benchmark('medium', RESTORE_LADDER)
    }
    return benchmark('low', RESTORE_LADDER)
}
