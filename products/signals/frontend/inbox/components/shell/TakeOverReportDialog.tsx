import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { fullNameOrEmail } from 'lib/utils/strings'

import type { _UserApi } from 'products/signals/frontend/generated/api.schemas'

import { SignalReport } from '../../types'

interface OpenTakeOverReportDialogParams {
    report: Pick<SignalReport, 'assignee'>
    /** The other person who holds the claim, from `teammateClaimHolder`. */
    holder: _UserApi
    onConfirm: () => void
}

/** Asks before the user takes over a teammate's claim, because the server tells that person their work moved. */
export function openTakeOverReportDialog({ report, holder, onConfirm }: OpenTakeOverReportDialogParams): void {
    const holderName = fullNameOrEmail(holder)
    const holderLabel = report.assignee?.kind === 'agent' ? `${holderName}'s agent` : holderName
    LemonDialog.open({
        title: 'Take over this report?',
        description: `${holderLabel} is working on this report. If you take it over, we let ${holderName} know.`,
        primaryButton: {
            children: 'Take over',
            onClick: onConfirm,
            'data-attr': 'inbox-report-takeover-confirm',
        },
        secondaryButton: { children: 'Cancel' },
    })
}
