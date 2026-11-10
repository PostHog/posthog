import { LemonDialog } from 'lib/lemon-ui/LemonDialog'

import { InboxReportActionSurface, captureInboxReportAction } from '../../inboxAnalytics'
import { SignalReport } from '../../types'
import type { ImplementationClaimStep } from '../../utils/reportActions'
import { openTakeOverReportDialog } from './TakeOverReportDialog'

interface OpenImplementClaimDialogParams {
    report: SignalReport
    surface: InboxReportActionSurface
    step: Extract<ImplementationClaimStep, { kind: 'take_over' | 'confirm_own_agent' }>
    onConfirm: () => void
}

/** Asks before Create PR takes a teammate's claim, or starts a run while the user's own agent works on the report. */
export function openImplementClaimDialog({ report, surface, step, onConfirm }: OpenImplementClaimDialogParams): void {
    if (step.kind === 'take_over') {
        openTakeOverReportDialog({
            report,
            surface,
            holder: step.holder,
            confirmLabel: 'Take over and implement',
            startsRun: true,
            onConfirm,
        })
        return
    }
    let confirmed = false
    LemonDialog.open({
        title: 'Start another run?',
        description: 'Your agent is already working on this report. A PostHog run could open a second pull request.',
        primaryButton: {
            children: 'Start run',
            onClick: () => {
                confirmed = true
                onConfirm()
            },
            'data-attr': 'inbox-report-implement-beside-agent-confirm',
        },
        secondaryButton: { children: 'Cancel' },
        onAfterClose: () =>
            captureInboxReportAction({
                report,
                actionType: 'claim_dialog',
                surface,
                extra: { claim_step: 'confirm_own_agent', starts_run: true, confirmed },
            }),
    })
}
