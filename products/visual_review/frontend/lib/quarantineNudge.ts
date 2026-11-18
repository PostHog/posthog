import { dayjs } from 'lib/dayjs'

import type { ToleratedHashEntryApi } from '../generated/api.schemas'

// Same window the baselines overview uses for `tolerate_count_30d`.
export const QUARANTINE_NUDGE_WINDOW_DAYS = 30

// Same floor as the backend `VARIANT_PILEUP_MIN`, chosen to agree with it: at
// three accepted renderings a snapshot no longer has one rendering.
const QUARANTINE_NUDGE_MIN_INTENTIONAL = 3

// Auto tolerations cost nobody a click, so it takes more of them to mean the
// same thing. Each one is a distinct rendering the diff pipeline absorbed, and
// ten in a month is a snapshot that renders differently every few days.
const QUARANTINE_NUDGE_MIN_AUTO = 10

export interface RecentTolerations {
    manual: number
    agent: number
    auto: number
}

export function countRecentTolerations(toleratedHashes: ToleratedHashEntryApi[], now: dayjs.Dayjs): RecentTolerations {
    const cutoff = now.subtract(QUARANTINE_NUDGE_WINDOW_DAYS, 'day')
    const recent = toleratedHashes.filter((entry) => !dayjs(entry.created_at).isBefore(cutoff))
    return {
        manual: recent.filter((entry) => entry.reason === 'human').length,
        agent: recent.filter((entry) => entry.reason === 'agent').length,
        auto: recent.filter((entry) => entry.reason === 'auto_threshold').length,
    }
}

export function shouldSuggestQuarantine(counts: RecentTolerations): boolean {
    return counts.manual + counts.agent >= QUARANTINE_NUDGE_MIN_INTENTIONAL || counts.auto >= QUARANTINE_NUDGE_MIN_AUTO
}
