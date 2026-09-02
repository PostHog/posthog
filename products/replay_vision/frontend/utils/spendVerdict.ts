import { dayjs } from 'lib/dayjs'

import type { VisionQuotaApi } from '../generated/api.schemas'
import { formatCreditCount } from './credits'
import { type QuotaContribution, buildQuotaMeter } from './quotaContributions'
import type { QuotaProjection } from './quotaProjection'

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
    projection: QuotaProjection
    hasCap: boolean
}

const PILL_TAG_TYPES: Record<SpendVerdictKind, 'success' | 'warning' | 'danger' | 'muted'> = {
    safe: 'success',
    warning: 'warning',
    danger: 'danger',
    paused: 'danger',
    uncapped: 'muted',
}

/** LemonTag type carrying a verdict's colour, so every pill renders the same status the same way. */
export function verdictTagType(kind: SpendVerdictKind): 'success' | 'warning' | 'danger' | 'muted' {
    return PILL_TAG_TYPES[kind]
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

    if (!hasCap) {
        const monthly = contributions.reduce((sum, c) => (c.kind === 'monthly-rate' ? sum + c.credits : sum), 0)
        return {
            kind: 'uncapped',
            pillLabel: 'No spend limit',
            sentence: `${subject} projected to use ~${formatCreditCount(monthly)}/month.`,
            spentPct: 0,
            projectedPct: 0,
            periodEndPct,
            projection,
            hasCap,
        }
    }

    if (projection.exhausted) {
        return {
            kind: 'paused',
            pillLabel: onFreePlan ? 'Out of free credits' : 'Limit reached',
            sentence: onFreePlan
                ? `Scanning is paused until ${resetsOn}: the free credits are used up.`
                : `Scanning is paused until ${resetsOn}: the monthly spend limit is reached.`,
            spentPct: 100,
            projectedPct: 0,
            periodEndPct,
            projection,
            hasCap,
        }
    }

    // Over the displayed limit without the backend blocking (the startup cap clamps the display
    // below billing's limit): state the overshoot without claiming scanning is paused.
    if (projection.usedPct >= 100) {
        return {
            kind: 'danger',
            pillLabel: 'Over limit',
            sentence: `Spend has exceeded the ${limitNoun} for this period.`,
            spentPct,
            projectedPct,
            periodEndPct,
            projection,
            hasCap,
        }
    }

    if (model.status === 'danger') {
        const capDate = projection.capReachDate ? projection.capReachDate.format('MMM D') : null
        return {
            kind: 'danger',
            pillLabel: capDate ? `Limit by ${capDate}` : 'Over limit',
            sentence: capDate
                ? `${subject} on track to ${onFreePlan ? 'use up the free credits' : 'hit the monthly spend limit'} around ${capDate}.`
                : `${subject} projected to exceed the ${limitNoun} by ${resetsOn}.`,
            spentPct,
            projectedPct,
            periodEndPct,
            projection,
            hasCap,
        }
    }

    return {
        kind: model.status === 'warning' ? 'warning' : 'safe',
        pillLabel: model.status === 'warning' ? 'Nearing limit' : 'On track',
        sentence: `${subject} projected to use ${periodEndPct}% of the ${limitNoun} by ${resetsOn}.`,
        spentPct,
        projectedPct,
        periodEndPct,
        projection,
        hasCap,
    }
}

/** Days into the current period, floored at 0; drives the "today" position on trajectory charts. */
export function daysIntoPeriod(periodStart: string): number {
    return Math.max(dayjs().diff(dayjs(periodStart), 'day', true), 0)
}
