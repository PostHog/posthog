import type { InlineScanRequestApi, ScanOutcomeEnumApi } from '../generated/api.schemas'

/**
 * The config behind "Summarize this recording".
 *
 * Inline scans are keyed by a fingerprint of this whole config, so every project gets exactly one
 * scanner row for the button no matter how often it is pressed. Editing anything here forks a new
 * row per project and leaves the old summaries under the old one, so treat it as a versioned
 * identity rather than a string to tweak in passing.
 *
 * The prompt is a deliberate copy of the `session_summary` scanner template rather than a reference
 * to it. That template is user-facing and edited freely, and reading it here would make every edit
 * fork this scanner in every project. Keep the two in step by hand when the wording improves.
 *
 * `model` is deliberately absent: the server default applies, so the model can move without a
 * frontend deploy.
 */
export const SUMMARIZE_RECORDING_CONFIG: Pick<InlineScanRequestApi, 'prompt' | 'scanner_type' | 'scanner_config'> = {
    scanner_type: 'summarizer',
    prompt: "Summarize what the user did in this session: which pages they visited, what they tried to accomplish, and any notable moments like errors, confusion, or successful completions. Be concrete and don't speculate.",
    scanner_config: { length: 'medium' },
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
