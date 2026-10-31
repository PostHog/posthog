import type { HighlightFeedItemApi } from '../generated/api.schemas'
import type { HighlightFeedEmptyReason } from './highlightFeedEmptyState'

export const STALE_AFTER_MS = 2 * 24 * 60 * 60 * 1000

export type HighlightPicksStaleReason =
    | 'caught-up'
    | 'quiet-week'
    | 'drought'
    | 'quota-exhausted'
    | 'all-disabled'
    | 'all-capped'

export interface HighlightPicksStaleInput {
    picks: HighlightFeedItemApi[]
    blockReason: HighlightFeedEmptyReason
    droughtScannerIds: string[]
    now: Date
}

export function resolveHighlightPicksStaleReason({
    picks,
    blockReason,
    droughtScannerIds,
    now,
}: HighlightPicksStaleInput): HighlightPicksStaleReason | null {
    if (picks.length === 0) {
        return null
    }
    const newest = Math.max(...picks.map((pick) => new Date(pick.observation.created_at).getTime()))
    const old = now.getTime() - newest > STALE_AFTER_MS
    const allViewed = picks.every((pick) => pick.observation.viewed)
    if (!old && !allViewed) {
        return null
    }
    if (blockReason === 'quota-exhausted' || blockReason === 'all-disabled' || blockReason === 'all-capped') {
        return blockReason
    }
    if (droughtScannerIds.length > 0) {
        return 'drought'
    }
    return old ? 'quiet-week' : 'caught-up'
}
