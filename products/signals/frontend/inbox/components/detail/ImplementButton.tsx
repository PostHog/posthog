import { useActions, useValues } from 'kea'

import { IconCopy, IconPullRequest } from '@posthog/icons'
import { LemonButton, lemonToast } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { addProjectIdIfMissing } from 'lib/utils/kea-router'
import { urls } from 'scenes/urls'

import { captureInboxReportAction } from '../../inboxAnalytics'
import { inboxTaskKickoffLogic } from '../../inboxTaskKickoffLogic'
import { ImplementationSlotClaim, inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { SignalReport } from '../../types'
import { buildReportImplementationPrompt } from './buildReportImplementationPrompt'

// A report funds one implementation at a time. The two claims send the reader to the same task but
// for different reasons, so they read differently: one run is still working, the other already
// shipped the PR.
const SLOT_CLAIM_DISABLED_REASON: Record<ImplementationSlotClaim, string> = {
    in_flight: 'A pull request run is already in progress for this report. Open it in the task log to follow it.',
    shipped_pr: 'This report already has a pull request. Open it in the task log to continue it.',
}

export function ImplementButton({ report }: { report: SignalReport }): JSX.Element {
    const { isCreatingPr, aiConsentDisabledReason } = useValues(inboxTaskKickoffLogic)
    // Already mounted by `ReportDetail`, so this reads the loaded value rather than starting a fetch.
    const { implementationSlotClaim } = useValues(inboxReportDetailLogic({ reportId: report.id, report }))
    const { createPrFromReport } = useActions(inboxTaskKickoffLogic)
    const reportUrl = `${window.location.origin}${addProjectIdIfMissing(urls.inboxReport('reports', report.id))}`

    const disabledReason =
        aiConsentDisabledReason ??
        (implementationSlotClaim ? SLOT_CLAIM_DISABLED_REASON[implementationSlotClaim] : undefined)

    const submit = (): void => {
        if (isCreatingPr || implementationSlotClaim) {
            return
        }
        if (aiConsentDisabledReason) {
            lemonToast.error(aiConsentDisabledReason)
            return
        }
        captureInboxReportAction({
            report,
            actionType: 'create_pr',
            surface: 'detail_pane',
            extra: { has_feedback: false },
        })
        createPrFromReport(report, undefined)
    }

    const copyImplementationPrompt = async (): Promise<void> => {
        const copied = await copyToClipboard(
            buildReportImplementationPrompt(report, reportUrl),
            'implementation prompt'
        )
        if (copied) {
            captureInboxReportAction({
                report,
                actionType: 'copy_implementation_prompt',
                surface: 'detail_pane',
            })
        }
    }

    return (
        <LemonButton
            type="primary"
            size="small"
            icon={<IconPullRequest />}
            onClick={submit}
            loading={isCreatingPr}
            disabledReason={disabledReason}
            tooltip="Implement this report with PostHog"
            data-attr="inbox-report-create-pr"
            sideAction={{
                tooltip: 'More implementation options',
                'aria-label': 'More implementation options',
                'data-attr': 'inbox-report-create-pr-steer',
                dropdown: {
                    placement: 'bottom-end',
                    overlay: (
                        <div className="w-72 p-1">
                            <LemonButton
                                fullWidth
                                icon={<IconCopy />}
                                onClick={() => void copyImplementationPrompt()}
                                data-attr="inbox-report-copy-implementation-prompt"
                            >
                                <span className="flex flex-col items-start">
                                    <span>Use your agent</span>
                                    <span className="text-xs font-normal text-secondary">Copy the report prompt</span>
                                </span>
                            </LemonButton>
                        </div>
                    ),
                },
            }}
        >
            Implement
        </LemonButton>
    )
}
