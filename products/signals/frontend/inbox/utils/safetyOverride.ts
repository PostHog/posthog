// Why PostHog declined to implement a report on its own, in words the confirmation can show.
// Pure so the detail pane and the list row show the same sentence, and so the wording is testable
// without a render.

import { SignalReport, SignalReportArtefact, SignalReportStatus } from '../types'

/**
 * The safety judge's reason for rejecting this report, from its newest `safety_judgment` artefact.
 *
 * Null when the report carries no verdict, when the newest verdict approves it (an earlier override
 * is itself a safe verdict, so it must not read as a fresh rejection), or when the verdict left no
 * explanation. The newest row of a status type is the canonical one, and ISO-8601 `created_at`
 * strings compare chronologically, so this does not depend on the API's response ordering.
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
 * What the confirmation leads with: what PostHog decided about this report, and why.
 * `judgeExplanation` comes from {@link latestUnsafeSafetyExplanation}. Without one, the report's
 * status is the most specific thing we can say, so the copy says only that.
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
