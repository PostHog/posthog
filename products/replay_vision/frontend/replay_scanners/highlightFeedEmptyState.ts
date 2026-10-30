import type { ReplayScannerApi, VisionQuotaApi } from '../generated/api.schemas'

/**
 * Why the highlight feed came back with nothing. Each value is a different answer for the
 * reader, so they get different copy and a different next step.
 */
export type HighlightFeedEmptyReason =
    | 'replay-off'
    | 'no-recordings'
    | 'no-scanners'
    | 'quota-exhausted'
    | 'all-disabled'
    | 'all-capped'
    | 'filtered'
    | 'quiet-window'

/** The reasons no new sessions can reach the feed, whether or not it still has older ones to show. */
export type HighlightFeedBlockReason = 'quota-exhausted' | 'all-disabled' | 'all-capped'

/** What blocks the feed, and where the reader lifts the block. Both the banner and the empty note use it. */
export const HIGHLIGHT_FEED_BLOCKS: Record<
    HighlightFeedBlockReason,
    {
        cause: string
        fix: string
        actionLabel: string
        tab: 'scanners' | 'usage'
        dataAttr: string
        bannerDataAttr: string
    }
> = {
    'all-disabled': {
        cause: 'All scanners on this project are off.',
        fix: 'Turn one on to scan new recordings again.',
        actionLabel: 'See scanners',
        tab: 'scanners',
        dataAttr: 'vision-highlight-feed-see-scanners',
        bannerDataAttr: 'vision-highlight-feed-banner-see-scanners',
    },
    'quota-exhausted': {
        cause: 'Your Replay Vision credits are used up for this period.',
        fix: 'Raise the limit to scan new recordings again.',
        actionLabel: 'See usage',
        tab: 'usage',
        dataAttr: 'vision-highlight-feed-see-usage',
        bannerDataAttr: 'vision-highlight-feed-banner-see-usage',
    },
    'all-capped': {
        cause: 'Every running scanner has reached its credit limit for this period.',
        fix: "Raise a scanner's limit to scan new recordings again.",
        actionLabel: 'See usage',
        tab: 'usage',
        dataAttr: 'vision-highlight-feed-see-usage',
        bannerDataAttr: 'vision-highlight-feed-banner-see-usage',
    },
}

export function isHighlightFeedBlock(reason: HighlightFeedEmptyReason | null): reason is HighlightFeedBlockReason {
    return reason !== null && reason in HIGHLIGHT_FEED_BLOCKS
}

export interface HighlightFeedEmptyInput {
    scanners: ReplayScannerApi[]
    /** Null when the snapshot has not answered, which reads here as "no block seen". */
    quota: VisionQuotaApi | null
    /** Null while the team has not loaded, which also reads as "no block seen". */
    sessionRecordingOptIn: boolean | null
    hasFeedFilters: boolean
    hasRecordings?: boolean | null
}

/**
 * Resolves the one reason to show. A block the reader cannot lift from this tab is checked before
 * their own filters, because clearing those would leave the feed just as empty.
 */
export function resolveHighlightFeedEmptyReason({
    scanners,
    quota,
    sessionRecordingOptIn,
    hasFeedFilters,
    hasRecordings = null,
}: HighlightFeedEmptyInput): HighlightFeedEmptyReason {
    if (sessionRecordingOptIn === false) {
        return 'replay-off'
    }
    if (scanners.length === 0) {
        if (hasRecordings === false) {
            return 'no-recordings'
        }
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
    return hasRecordings === false ? 'no-recordings' : 'quiet-window'
}
