import type { ReplayScannerApi, ScanOutcomeEnumApi } from '../generated/api.schemas'
import { isSummarizerScanner } from '../replay_scanners/types'

/**
 * The stored preference for "run the built-in prompt", as opposed to no preference at all.
 *
 * Scanner ids are UUIDs, so this cannot collide with one. The two cases have to stay distinct: a team
 * with a single summarizer gets it by default, but must still be able to choose the built-in prompt
 * and have that stick.
 */
export const BUILT_IN_SUMMARIZER = 'built-in'

/**
 * Which summarizer the button runs, or null for the built-in prompt.
 *
 * A stored preference wins while the scanner it names still exists, so a deleted scanner falls back
 * rather than leaving the button pointed at nothing. With no usable preference, a lone summarizer is
 * an unambiguous choice and anything else is not: picking one of several deliberate prompts for the
 * user would silently favor one, so that case runs the built-in prompt and says so.
 */
export function resolveSummarizer(scanners: ReplayScannerApi[], preferredId: string | null): ReplayScannerApi | null {
    if (preferredId === BUILT_IN_SUMMARIZER) {
        return null
    }
    const summarizers = scanners.filter(isSummarizerScanner)
    const preferred = preferredId ? summarizers.find((scanner) => scanner.id === preferredId) : undefined
    if (preferred) {
        return preferred
    }
    return summarizers.length === 1 ? summarizers[0] : null
}

export interface SummarizeOutcomeMessage {
    level: 'success' | 'info' | 'warning' | 'error'
    message: string
}

/**
 * What to tell the user about a one-session inline scan.
 *
 * The endpoint answers 202 whether or not anything started, reporting the reason per session, so
 * only the outcome distinguishes a summary that is on its way from one the quota refused. A cap is
 * a warning rather than an error, matching how the scanner run tab reports the same two outcomes.
 *
 * `already_scanned` is absent on purpose: a settled row may be unreadable here, so its message
 * depends on what a reload returns and is decided by the caller, not this pure mapping.
 */
export function summarizeOutcomeMessage(outcome: ScanOutcomeEnumApi | undefined): SummarizeOutcomeMessage {
    switch (outcome) {
        case 'started':
            return { level: 'success', message: 'Summary started' }
        case 'already_running':
            return { level: 'info', message: 'A summary of this recording is already being generated.' }
        case 'skipped_quota':
            return { level: 'warning', message: "You've hit the monthly Replay vision credit limit." }
        case 'skipped_limit':
            return { level: 'warning', message: 'Too many scans are running right now. Try again in a moment.' }
        default:
            return { level: 'error', message: "Couldn't start the summary. Try again in a moment." }
    }
}
