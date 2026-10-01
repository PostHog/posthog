import type { ReplayScannerApi, VisionQuotaApi } from '../generated/api.schemas'

/**
 * Why the What to watch feed came back with nothing. Each value is a different answer for the
 * reader, so they get different copy and a different next step.
 */
export type WatchFeedEmptyReason =
    | 'no-scanners'
    | 'quota-exhausted'
    | 'all-disabled'
    | 'all-capped'
    | 'filtered'
    | 'quiet-window'

export interface WatchFeedEmptyInput {
    scanners: ReplayScannerApi[]
    /** Null when the snapshot has not answered, which reads here as "no block seen". */
    quota: VisionQuotaApi | null
    hasFeedFilters: boolean
}

/**
 * Resolves the one reason to show. A block the reader cannot lift from this tab is checked before
 * their own filters, because clearing those would leave the feed just as empty.
 */
export function resolveWatchFeedEmptyReason({
    scanners,
    quota,
    hasFeedFilters,
}: WatchFeedEmptyInput): WatchFeedEmptyReason {
    if (scanners.length === 0) {
        // The scene gate answers this one first, so the feed sees it only when the setup probe
        // failed open. The tab still has to offer the way in.
        return 'no-scanners'
    }
    // An exhausted budget skips the sweeps whatever the scanners say, so it is checked before them.
    if (quota?.exhausted) {
        return 'quota-exhausted'
    }
    const enabledScanners = scanners.filter((scanner) => scanner.enabled)
    if (enabledScanners.length === 0) {
        return 'all-disabled'
    }
    if (enabledScanners.every((scanner) => scanner.limit_reached)) {
        return 'all-capped'
    }
    if (hasFeedFilters) {
        return 'filtered'
    }
    return 'quiet-window'
}
