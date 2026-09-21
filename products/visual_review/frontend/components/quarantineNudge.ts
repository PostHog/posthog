import { dayjs } from 'lib/dayjs'

import type { ToleratedHashEntryApi } from '../generated/api.schemas'

// Same window the baselines overview uses for `tolerate_count_30d`.
export const QUARANTINE_NUDGE_WINDOW_DAYS = 30

// Matches the backend `VARIANT_PILEUP_MIN`: at three accepted renderings a
// baseline no longer describes one rendering.
const QUARANTINE_NUDGE_MIN_INTENTIONAL = 3

// Auto tolerations cost nobody a click, so it takes more of them to mean the
// same thing. Each one is a distinct rendering the diff pipeline absorbed, and
// ten in a month is a snapshot that renders differently every few days.
const QUARANTINE_NUDGE_MIN_AUTO = 10

export interface RecentTolerations {
    intentional: number
    auto: number
}

export function countRecentTolerations(toleratedHashes: ToleratedHashEntryApi[], now: dayjs.Dayjs): RecentTolerations {
    const cutoff = now.subtract(QUARANTINE_NUDGE_WINDOW_DAYS, 'day')
    const recent = toleratedHashes.filter((entry) => dayjs(entry.created_at).isAfter(cutoff))
    return {
        intentional: recent.filter((entry) => entry.reason === 'human' || entry.reason === 'agent').length,
        auto: recent.filter((entry) => entry.reason === 'auto_threshold').length,
    }
}

export function shouldSuggestQuarantine(counts: RecentTolerations): boolean {
    return counts.intentional >= QUARANTINE_NUDGE_MIN_INTENTIONAL || counts.auto >= QUARANTINE_NUDGE_MIN_AUTO
}
