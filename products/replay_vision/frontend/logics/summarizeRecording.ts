import type { InlineScanRequestApi, ScanOutcomeEnumApi } from '../generated/api.schemas'

/**
 * The config behind "Summarize this recording".
 *
 * Inline scans are keyed by a fingerprint of this whole config, so every project gets exactly one
 * scanner row for the button no matter how often it is pressed. Editing anything here forks a new
 * row per project and leaves the old summaries under the old one, so treat it as a versioned
 * identity rather than a string to tweak in passing.
 *
 * `model` is deliberately absent: the server default applies, so the model can move without a
 * frontend deploy.
 */
export const SUMMARIZE_RECORDING_CONFIG: Pick<InlineScanRequestApi, 'prompt' | 'scanner_type' | 'scanner_config'> = {
    scanner_type: 'summarizer',
    prompt: 'Summarize what happened in this session. Cover what the user was trying to do, the path they took, and anything that got in their way.',
    scanner_config: { length: 'medium' },
}

export interface SummarizeOutcomeMessage {
    level: 'success' | 'info' | 'error'
    message: string
}

/**
 * What to tell the user about a one-session inline scan.
 *
 * The endpoint answers 202 whether or not anything started, reporting the reason per session, so
 * only the outcome distinguishes a summary that is on its way from one the quota refused.
 */
export function summarizeOutcomeMessage(outcome: ScanOutcomeEnumApi | undefined): SummarizeOutcomeMessage {
    switch (outcome) {
        case 'started':
            return { level: 'success', message: 'Summary started' }
        case 'already_scanned':
        case 'already_running':
            return { level: 'info', message: 'This recording has already been summarized.' }
        case 'skipped_quota':
            return { level: 'error', message: "You've used all your Replay vision credits for this month." }
        case 'skipped_limit':
            return { level: 'error', message: 'Too many scans are running right now. Try again in a moment.' }
        default:
            return { level: 'error', message: "Couldn't start the summary. Try again in a moment." }
    }
}
