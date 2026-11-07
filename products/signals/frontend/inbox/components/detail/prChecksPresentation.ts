import type { PullRequestCheckApi } from 'products/signals/frontend/generated/api.schemas'

export type CheckVariant = 'failure' | 'cancelled' | 'pending' | 'stale' | 'success' | 'neutral'

export const CHECK_VARIANT_LABELS: Record<CheckVariant, string> = {
    failure: 'Failed',
    cancelled: 'Cancelled',
    pending: 'Running',
    stale: 'Stale',
    success: 'Successful',
    neutral: 'Skipped',
}

// Failed first, then in-flight, then the rest — the buckets worth a human's attention lead.
export const CHECK_VARIANT_ORDER: CheckVariant[] = ['failure', 'pending', 'cancelled', 'stale', 'success', 'neutral']

/** Collapse a GitHub check's (status, conclusion) pair into one of the buckets we render. */
export function resolveCheckVariant(check: PullRequestCheckApi): CheckVariant {
    if (check.status !== 'completed') {
        return 'pending'
    }
    switch (check.conclusion) {
        case 'success':
            return 'success'
        case 'failure':
        case 'timed_out':
        case 'action_required':
        case 'startup_failure':
            return 'failure'
        case 'cancelled':
            return 'cancelled'
        case 'stale':
            return 'stale'
        default:
            // neutral / skipped / null-on-completed
            return 'neutral'
    }
}

/** Resolve each check's variant once, then sort and count off it, so the buckets worth a human's attention lead. */
export function summarizePrChecks(checks: readonly PullRequestCheckApi[] | null): {
    sorted: { check: PullRequestCheckApi; variant: CheckVariant }[]
    counts: Record<CheckVariant, number>
} {
    const sorted = (checks ?? [])
        .map((check) => ({ check, variant: resolveCheckVariant(check) }))
        .sort((a, b) => CHECK_VARIANT_ORDER.indexOf(a.variant) - CHECK_VARIANT_ORDER.indexOf(b.variant))
    const counts = sorted.reduce<Record<CheckVariant, number>>(
        (result, { variant }) => {
            result[variant] += 1
            return result
        },
        { failure: 0, cancelled: 0, pending: 0, stale: 0, success: 0, neutral: 0 }
    )
    return { sorted, counts }
}
