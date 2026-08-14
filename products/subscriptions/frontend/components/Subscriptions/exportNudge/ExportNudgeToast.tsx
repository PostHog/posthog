import { LemonButton } from 'lib/lemon-ui/LemonButton'

import {
    ExportNudgeCandidate,
    claimExportNudge,
    subscriptionTargetFor,
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

export function claimExportNudgeMessage(candidate: ExportNudgeCandidate): ExportNudgeMessage | null {
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
                        openSubscriptionFromNudge(subscriptionTargetFor(candidate.subject), {
                            via: SUBSCRIPTION_PREFILL_PARAMS.viaExport,
                        })
                    }}
                >
                    Set up recurring updates
                </LemonButton>
            </span>
        )
    }
}
