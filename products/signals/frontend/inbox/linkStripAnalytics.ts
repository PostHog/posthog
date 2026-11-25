import type { ReportLinkSummaryApi } from 'products/signals/frontend/generated/api.schemas'

import { baseReportProperties, captureInboxEvent, INBOX_EVENTS } from './inboxAnalytics'
import type { SignalReport } from './types'

/** What a click on a card's link strip opened. */
export type InboxLinkStripTarget = 'linked_report' | 'plan_step' | 'other_link'

/**
 * A click on a card's link strip. With the strip kinds on `Inbox reports impressed` as the denominator,
 * this says whether people follow links from the list, and for which kinds. It lives apart from
 * `inboxAnalytics`, which every logged-in page loads, because only the inbox list renders a strip.
 */
export function captureInboxReportLinkStripClicked(params: {
    report: SignalReport
    summary: ReportLinkSummaryApi
    target: InboxLinkStripTarget
    linkedReportId: string
    /** The link kind of the report that was opened, for an `other_link` click. */
    linkedKind?: string | null
    /** The 1-based position of the opened layer, for a `plan_step` click. */
    stepPosition?: number | null
}): void {
    const ownStepIndex = params.summary.plan?.steps.findIndex((step) => step.id === params.report.id) ?? -1
    captureInboxEvent(INBOX_EVENTS.REPORT_LINK_STRIP_CLICKED, {
        ...baseReportProperties(params.report),
        strip_kind: params.summary.kind,
        target: params.target,
        linked_report_id: params.linkedReportId,
        linked_kind: params.linkedKind ?? null,
        step_position: params.stepPosition ?? null,
        step_count: params.summary.plan?.steps.length ?? null,
        own_step_position: ownStepIndex >= 0 ? ownStepIndex + 1 : null,
        other_link_count: params.summary.other_links.length,
    })
}
