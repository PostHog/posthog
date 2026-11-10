import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { fullNameOrEmail } from 'lib/utils/strings'

import type { _UserApi } from 'products/signals/frontend/generated/api.schemas'

import { InboxReportActionSurface, captureInboxReportAction } from '../../inboxAnalytics'
import { SignalReport } from '../../types'

interface OpenTakeOverReportDialogParams {
    report: SignalReport
    surface: InboxReportActionSurface
    /** The other person who holds the claim, from `teammateClaimHolder`. */
    holder: _UserApi
    /** Names what confirming does when it does more than take the claim. */
    confirmLabel?: string
    /** Whether confirming also starts an implementation run. */
    startsRun?: boolean
    onConfirm: () => void
}

/** Asks before the user takes over a teammate's claim, because the server tells that person their work moved. */
export function openTakeOverReportDialog({
    report,
    surface,
    holder,
    confirmLabel = 'Take over',
    startsRun = false,
    onConfirm,
}: OpenTakeOverReportDialogParams): void {
    let confirmed = false
    const holderName = fullNameOrEmail(holder)
    const holderLabel = report.assignee?.kind === 'agent' ? `${holderName}'s agent` : holderName
    LemonDialog.open({
        title: 'Take over this report?',
        description: `${holderLabel} is working on this report. If you take it over, we let ${holderName} know.`,
        primaryButton: {
            children: confirmLabel,
            onClick: () => {
                confirmed = true
                onConfirm()
            },
            'data-attr': 'inbox-report-takeover-confirm',
        },
        secondaryButton: { children: 'Cancel' },
        // Runs on every close, so a cancel, Escape and a backdrop click all count as not confirmed.
        onAfterClose: () =>
            captureInboxReportAction({
                report,
                actionType: 'claim_dialog',
                surface,
                extra: { claim_step: 'take_over', starts_run: startsRun, confirmed },
            }),
    })
}
