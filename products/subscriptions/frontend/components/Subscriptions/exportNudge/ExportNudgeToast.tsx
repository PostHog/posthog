import { useState } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { ToastActionButton, ToastButton } from 'lib/lemon-ui/LemonToast/LemonToast'

import {
    ExportNudgeCandidate,
    claimExportNudge,
    subjectNoun,
    subscriptionTargetFor,
} from 'products/subscriptions/frontend/components/Subscriptions/exportNudge/exportNudgeLogic'
import {
    SUBSCRIPTION_PREFILL_PARAMS,
    openSubscriptionFromNudge,
} from 'products/subscriptions/frontend/components/Subscriptions/subscriptionNudge'

/**
 * Builds the toast's message. The offer rides along until it is followed, and lays the toast's own
 * action out beside its CTA so the two sit on one row. `toastId` is required because that action
 * closes its own toast, and closing without one closes every toast on screen.
 */
export type ExportNudgeMessage = (
    headline: string,
    toastId: number | string,
    action?: ToastButton
) => string | JSX.Element

function subjectLabel(candidate: ExportNudgeCandidate): JSX.Element | string {
    if (candidate.name) {
        return <span className="italic">{candidate.name}</span>
    }
    return subjectNoun(candidate.subject)
}

/**
 * The toast on screen is static children, so flipping a flag in the closure does not remove this
 * button from it. Its own state does, which also stops a second click reporting a second follow.
 */
function SubscribeButton({ onFollow }: { onFollow: () => void }): JSX.Element {
    const [followed, setFollowed] = useState(false)
    return (
        <LemonButton
            type="primary"
            size="small"
            data-attr="export-nudge-toast-cta"
            disabledReason={followed ? 'Opening the subscription form' : undefined}
            onClick={() => {
                setFollowed(true)
                onFollow()
            }}
        >
            Subscribe
        </LemonButton>
    )
}

export function claimExportNudgeMessage(candidate: ExportNudgeCandidate): ExportNudgeMessage | null {
    if (!claimExportNudge(candidate.subject)) {
        return null
    }

    let accepted = false
    return (headline: string, toastId: number | string, action?: ToastButton) => {
        // One layout either way. Following the offer only takes the offer away: this message still
        // owns the row, so it keeps rendering the export's own action, and a file waiting to be
        // downloaded does not lose its button.
        if (accepted && !action) {
            return headline
        }
        return (
            <span className="flex flex-col items-start gap-1.5 min-w-0">
                <span>{headline}</span>
                {!accepted && (
                    <span className="text-xs text-secondary leading-snug">
                        Want this on a schedule? We can send you a copy of {subjectLabel(candidate)} every week.
                    </span>
                )}
                {/* The toast body gives every button a horizontal margin, which would push this row
                    off the text above it and space the two buttons apart. */}
                <span className="flex flex-wrap items-center gap-2 *:m-0!">
                    {!accepted && (
                        <SubscribeButton
                            onFollow={() => {
                                accepted = true
                                openSubscriptionFromNudge(subscriptionTargetFor(candidate.subject), {
                                    via: SUBSCRIPTION_PREFILL_PARAMS.viaExport,
                                })
                            }}
                        />
                    )}
                    {action && <ToastActionButton button={action} toastId={toastId} />}
                </span>
            </span>
        )
    }
}
