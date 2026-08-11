import type { VisionQuotaApi } from '../generated/api.schemas'
import {
    QUOTA_STATUS_STYLES,
    QUOTA_WARN_THRESHOLD,
    type QuotaProjection,
    type QuotaStatus,
    hasCreditLimit,
    projectQuota,
} from './quotaProjection'

/** Backfill commitments, wherever they appear: a hue no status can take, so the two never collide. */
export const QUOTA_BACKFILL_CLASS = 'bg-brand-blue'
/** The rest of the fleet's scanners, when a surface is singling one scanner out. */
export const QUOTA_OTHER_SCANNERS_CLASS = 'bg-accent'
/** Marks the contribution that should carry the card's status colour. */
export const QUOTA_STATUS_CLASS = 'status'

/**
 * Something a surface adds to the spend meter on top of what the period has already spent.
 *
 * `kind` is the point of this type. A scanner estimate is a monthly *rate*, so it lands in this
 * period only in proportion to the days left; a backfill is charged once, when it runs. Feeding a
 * one-off through the rate path shrinks it to a fraction of itself, which is the bug this prevents.
 */
export interface QuotaContribution {
    key: string
    label: string
    credits: number
    kind: 'monthly-rate' | 'one-off'
    barClass: string
    striped?: boolean
}

export interface QuotaMeterSegmentModel {
    key: string
    label: string
    pct: number
    barClass: string
    striped?: boolean
}

export interface QuotaMeterModel {
    projection: QuotaProjection
    /** One verdict for the whole card, counting every contribution the bar draws. */
    status: QuotaStatus
    /** Bar segments in render order, already as percentages of the limit. */
    segments: QuotaMeterSegmentModel[]
    /** Where the period lands counting every contribution; exceeds 100 on overshoot. */
    periodEndPct: number
    hasCap: boolean
}

/** The org's own commitments, correctly typed: scanners are a rate, backfills are not. */
export function fleetContributions(quota: VisionQuotaApi | null): QuotaContribution[] {
    return [
        {
            key: 'backfills',
            label: 'Backfills',
            credits: quota?.backfills_committed_credits ?? 0,
            kind: 'one-off',
            barClass: QUOTA_BACKFILL_CLASS,
        },
        {
            key: 'scanners',
            label: 'Projected (scanners)',
            credits: quota?.scanners_monthly_credits ?? 0,
            kind: 'monthly-rate',
            barClass: QUOTA_STATUS_CLASS,
            striped: true,
        },
    ]
}

/**
 * Turn contributions into meter segments, in one place.
 *
 * Surfaces say what they are adding and how it is charged. They never convert credits to
 * percentages, order segments, or compute the headline number, because doing that per card is what
 * produced a one-off pro-rated into invisibility and a headline that disagreed with its own bar.
 */
export function buildQuotaMeter(quota: VisionQuotaApi | null, contributions: QuotaContribution[]): QuotaMeterModel {
    const hasCap = hasCreditLimit(quota)
    const cap = hasCap ? quota.credit_limit : 0
    const rates = contributions.filter((c) => c.kind === 'monthly-rate')
    const rateTotal = rates.reduce((sum, c) => sum + c.credits, 0)
    // The contributions are the whole projection, so move `projectQuota` off the stored fleet rate onto them.
    const projection = projectQuota(quota, rateTotal - (quota?.projected_monthly_credits ?? 0))

    const asPct = (credits: number): number => (hasCap && cap > 0 ? (credits / cap) * 100 : 0)
    const segments = contributions.map((c) => ({
        key: c.key,
        label: c.label,
        barClass: c.barClass,
        striped: c.striped,
        // Rate contributions share the already pro-rated projection, split by weight, so the parts sum to
        // exactly what the projection says rather than drifting from it.
        pct:
            c.kind === 'one-off'
                ? asPct(c.credits)
                : rateTotal > 0
                  ? (projection.projectedPct * c.credits) / rateTotal
                  : 0,
    }))

    const periodEndPct = Math.round(projection.usedPct + segments.reduce((sum, s) => sum + s.pct, 0))
    // One verdict, from the same total the bar draws. Deriving it per card produced a headline that
    // could read green beside a bar sitting past the limit marker.
    const status: QuotaStatus =
        projection.status === 'danger' || periodEndPct >= 100
            ? 'danger'
            : periodEndPct >= QUOTA_WARN_THRESHOLD * 100
              ? 'warning'
              : 'safe'

    return {
        projection,
        status,
        // The status colour is resolved here so no caller patches a segment after the fact.
        segments: segments.map((segment) =>
            segment.barClass === QUOTA_STATUS_CLASS
                ? { ...segment, barClass: QUOTA_STATUS_STYLES[status].bar }
                : segment
        ),
        periodEndPct,
        hasCap,
    }
}
