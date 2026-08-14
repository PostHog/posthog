import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { ToastActionButton, ToastButton } from 'lib/lemon-ui/LemonToast/LemonToast'

import {
    ExportNudgeCandidate,
    claimExportNudge,
    subscriptionTargetFor,
} from 'products/subscriptions/frontend/components/Subscriptions/exportNudge/exportNudgeLogic'
import {
    SUBSCRIPTION_PREFILL_PARAMS,
    openSubscriptionFromNudge,
} from 'products/subscriptions/frontend/components/Subscriptions/subscriptionNudge'

/**
 * Builds the toast's message for a given headline. The offer rides along until it is followed, and
 * lays out the toast's own action beside its CTA so the two sit on one row.
 */
export type ExportNudgeMessage = (headline: string, action?: ToastButton) => string | JSX.Element

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
    return (headline: string, action?: ToastButton) => {
        if (accepted) {
            // The offer is spent, but this message still owns the layout, so it keeps rendering the
            // export's own action — otherwise a file waiting to be downloaded loses its button.
            return action ? (
                <span className="flex items-center gap-2 *:m-0!">
                    <span className="grow overflow-hidden text-ellipsis">{headline}</span>
                    <ToastActionButton button={action} />
                </span>
            ) : (
                headline
            )
        }
        return (
            <span className="flex flex-col items-start gap-1.5 min-w-0">
                <span>{headline}</span>
                <span className="text-xs text-secondary leading-snug">
                    Want this on a schedule? We can send you a copy of {subjectLabel(candidate)} every week.
                </span>
                {/* The toast body gives every button a horizontal margin, which would push this row
                    off the text above it and space the two buttons apart. */}
                <span className="flex flex-wrap items-center gap-2 *:m-0!">
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
                        Subscribe
                    </LemonButton>
                    {action && <ToastActionButton button={action} />}
                </span>
            </span>
        )
    }
}
