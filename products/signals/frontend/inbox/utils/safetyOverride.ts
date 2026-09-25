// Why PostHog declined to implement a report on its own, in words the confirmation can show.
// Pure so the detail pane and the list row show the same sentence.

import { SignalReport, SignalReportArtefact, SignalReportStatus } from '../types'

/**
 * The safety judge's reason for rejecting this report, from its newest `safety_judgment` artefact.
 * Null when the newest verdict approves the report, because an earlier override is itself a safe
 * verdict and must not read back as a fresh rejection.
 *
 * Selection compares ISO-8601 `created_at`, so it does not rely on the API's response ordering.
 */
export function latestUnsafeSafetyExplanation(artefacts: SignalReportArtefact[] | null): string | null {
    let latest: SignalReportArtefact | null = null
    for (const artefact of artefacts ?? []) {
        if (artefact.type === 'safety_judgment' && (!latest || artefact.created_at > latest.created_at)) {
            latest = artefact
        }
    }
    if (!latest || latest.content?.choice !== false) {
        return null
    }
    const explanation = latest.content?.explanation
    return typeof explanation === 'string' && explanation.trim() ? explanation.trim() : null
}

/**
 * What the confirmation leads with. Without a `judgeExplanation`, the report's status is the most
 * specific thing we can say, so the copy says only that rather than claiming a verdict.
 */
export function safetyOverrideReason(report: SignalReport, judgeExplanation: string | null): string {
    if (judgeExplanation) {
        return `PostHog didn't implement this report on its own. Its safety check flagged the report's content: "${judgeExplanation}"`
    }
    if (report.status === SignalReportStatus.FAILED) {
        return "PostHog didn't implement this report on its own. The run that researched it failed."
    }
    if (report.status === SignalReportStatus.SUPPRESSED) {
        return "This report is dismissed, so PostHog didn't implement it."
    }
    return "PostHog hasn't researched this report yet, so it hasn't decided whether the report holds work to do."
}
