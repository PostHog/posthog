import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { InsightShortId } from '~/types'

import {
    ExportNudgeCandidate,
    ExportNudgeSubject,
    claimExportNudge,
} from 'products/subscriptions/frontend/components/Subscriptions/exportNudge/exportNudgeLogic'
import {
    SUBSCRIPTION_PREFILL_PARAMS,
    openSubscriptionFromNudge,
} from 'products/subscriptions/frontend/components/Subscriptions/subscriptionNudge'

/** Builds the toast's message for a given headline. The offer rides along until it is followed. */
export type ExportNudgeMessage = (headline: string) => string | JSX.Element

function subjectLabel(candidate: ExportNudgeCandidate): JSX.Element | string {
    if (candidate.name) {
        return <span className="italic">{candidate.name}</span>
    }
    return candidate.subject.kind === 'dashboard' ? 'this dashboard' : 'this insight'
}

function subscriptionTarget(subject: ExportNudgeSubject): { dashboardId?: number; insightShortId?: InsightShortId } {
    return subject.kind === 'dashboard'
        ? { dashboardId: subject.dashboardId }
        : { insightShortId: subject.insightShortId }
}

export function claimExportNudgeMessage(candidate: ExportNudgeCandidate, toastId: string): ExportNudgeMessage | null {
    if (!claimExportNudge(candidate.subject)) {
        return null
    }

    let accepted = false
    return (headline: string) => {
        if (accepted) {
            return headline
        }
        return (
            <span className="flex flex-col items-start gap-1.5 min-w-0">
                <span>{headline}</span>
                <span className="text-xs text-secondary leading-snug">
                    Want this on a schedule? We can send you a copy of {subjectLabel(candidate)} every week.
                </span>
                <LemonButton
                    type="primary"
                    size="small"
                    data-attr="export-nudge-toast-cta"
                    onClick={() => {
                        accepted = true
                        // The toast is the export's own, and while the render is still running its
                        // download button has not appeared yet. Closing it here would leave the
                        // finished file with nowhere to be claimed from.
                        openSubscriptionFromNudge(subscriptionTarget(candidate.subject), {
                            toastId,
                            via: SUBSCRIPTION_PREFILL_PARAMS.viaExport,
                            keepToast: true,
                        })
                    }}
                >
                    Set up recurring updates
                </LemonButton>
            </span>
        )
    }
}
