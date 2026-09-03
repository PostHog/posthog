import type { VisionQuotaApi } from '../generated/api.schemas'
import { formatCreditCount } from './credits'
import { type QuotaContribution, buildQuotaMeter } from './quotaContributions'
import { QUOTA_STATUS_STYLES, type QuotaProjection } from './quotaProjection'

export type SpendVerdictKind = 'safe' | 'warning' | 'danger' | 'paused' | 'uncapped'

export interface SpendVerdict {
    kind: SpendVerdictKind
    /** Short label for the status pill, e.g. "On track" or "Limit by Sep 21". */
    pillLabel: string
    /** One sentence stating the projection; the pill and the bar repeat it, never contradict it. */
    sentence: string
    /** Actual spend as a share of the limit, clamped to 0..100. */
    spentPct: number
    /** Projected additional spend as a share of the limit, clamped so spent + projected <= 100. */
    projectedPct: number
    /** Projected period-end share of the limit, unclamped (e.g. 124 when overshooting). */
    periodEndPct: number
    /** Projected period-end demand in credits, unclamped; null without a quota snapshot. */
    projectedDemandCredits: number | null
    projection: QuotaProjection
    hasCap: boolean
}

const TEXT_CLASS: Record<SpendVerdictKind, string> = {
    safe: QUOTA_STATUS_STYLES.safe.text,
    warning: QUOTA_STATUS_STYLES.warning.text,
    danger: QUOTA_STATUS_STYLES.danger.text,
    paused: QUOTA_STATUS_STYLES.danger.text,
    uncapped: 'text-secondary',
}

const COLOR_VAR: Record<SpendVerdictKind, string> = {
    safe: 'var(--success)',
    warning: 'var(--warning)',
    danger: 'var(--danger)',
    paused: 'var(--danger)',
    uncapped: 'var(--muted)',
}

/** Text colour class for a verdict, for headline numbers and captions. */
export function verdictTextClass(kind: SpendVerdictKind): string {
    return TEXT_CLASS[kind]
}

/** CSS colour variable for a verdict, for SVG marks that cannot take a class. */
export function verdictColorVar(kind: SpendVerdictKind): string {
    return COLOR_VAR[kind]
}

interface SpendVerdictOptions {
    /** Free-plan orgs run out of free credits; everyone else hits a spend limit they chose. */
    onFreePlan: boolean
    /** Subject plus verb, e.g. "Everything running is" or "Enabled scanners are". */
    subject?: string
}

/**
 * The one verdict a spend surface renders: pill, sentence, and bar widths from a single computation,
 * so a pill can never disagree with the bar beside it. Composition of the projection stays in the
 * contributions; this only decides how the total reads.
 */
export function spendVerdict(
    quota: VisionQuotaApi | null,
    contributions: QuotaContribution[],
    { onFreePlan, subject = 'Enabled scanners are' }: SpendVerdictOptions
): SpendVerdict {
    const model = buildQuotaMeter(quota, contributions)
    const { projection, periodEndPct, hasCap } = model
    const resetsOn = projection.resetsOn ?? 'period end'
    const limitNoun = onFreePlan ? 'free credits' : 'monthly spend limit'

    const spentPct = Math.min(Math.max(projection.usedPct, 0), 100)
    const projectedPct = Math.min(Math.max(periodEndPct, spentPct), 100) - spentPct

    const projectedDemandCredits = model.periodEndCredits
    const base = { spentPct, projectedPct, periodEndPct, projectedDemandCredits, projection, hasCap }

    if (!hasCap) {
        const { rateTotal: monthly, oneOffTotal: oneOffs } = model
        return {
            ...base,
            kind: 'uncapped',
            pillLabel: 'No spend limit',
            sentence: `${subject} projected to use ~${formatCreditCount(monthly)}/month${oneOffs > 0 ? ` plus ${formatCreditCount(oneOffs)} of backfills` : ''}.`,
            spentPct: 0,
            projectedPct: 0,
        }
    }

    if (projection.exhausted) {
        return {
            ...base,
            kind: 'paused',
            pillLabel: onFreePlan ? 'Out of free credits' : 'Limit reached',
            sentence: onFreePlan
                ? `Scanning is paused until ${resetsOn}: the free credits are used up.`
                : `Scanning is paused until ${resetsOn}: the monthly spend limit is reached.`,
            spentPct: 100,
            projectedPct: 0,
        }
    }

    // Over the displayed limit without the backend blocking (the startup cap clamps the display
    // below billing's limit): state the overshoot without claiming scanning is paused.
    if (projection.usedPct >= 100) {
        return {
            ...base,
            kind: 'danger',
            pillLabel: 'Over limit',
            sentence: `Spend has exceeded the ${limitNoun} for this period.`,
        }
    }

    if (model.status === 'danger') {
        const capDate = projection.capReachDate ? projection.capReachDate.format('MMM D') : null
        return {
            ...base,
            kind: 'danger',
            pillLabel: capDate ? `Limit by ${capDate}` : 'Over limit',
            sentence: capDate
                ? `${subject} on track to ${onFreePlan ? 'use up the free credits' : 'hit the monthly spend limit'} around ${capDate}.`
                : `${subject} projected to exceed the ${limitNoun} by ${resetsOn}.`,
        }
    }

    return {
        ...base,
        kind: model.status === 'warning' ? 'warning' : 'safe',
        pillLabel: model.status === 'warning' ? 'Nearing limit' : 'On track',
        sentence: `${subject} projected to use ${periodEndPct}% of the ${limitNoun} by ${resetsOn}.`,
    }
}
