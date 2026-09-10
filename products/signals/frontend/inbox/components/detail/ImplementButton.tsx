import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconCopy, IconPullRequest } from '@posthog/icons'
import { LemonButton, lemonToast } from '@posthog/lemon-ui'

import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { addProjectIdIfMissing } from 'lib/utils/kea-router'
import { urls } from 'scenes/urls'

import { captureInboxReportAction } from '../../inboxAnalytics'
import { inboxTaskKickoffLogic } from '../../inboxTaskKickoffLogic'
import { ImplementationSlotClaim, inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { SignalReport } from '../../types'
import { buildReportImplementationPrompt } from './buildReportImplementationPrompt'

const SLOT_CLAIM_DISABLED_REASON: Record<ImplementationSlotClaim, string> = {
    in_flight: 'A pull request run is already in progress for this report. Open it in the task log to follow it.',
    shipped_pr: 'This report already has a pull request. Open it in the task log to continue it.',
}

export function ImplementButton({ report }: { report: SignalReport }): JSX.Element {
    const { isCreatingPr, createPrDisabledReason } = useValues(inboxTaskKickoffLogic)
    const { implementationSlotClaim } = useValues(inboxReportDetailLogic({ reportId: report.id, report }))
    const { createPrFromReport } = useActions(inboxTaskKickoffLogic)
    const [instructions, setInstructions] = useState('')
    const reportUrl = `${window.location.origin}${addProjectIdIfMissing(urls.inboxReport('reports', report.id))}`

    const disabledReason =
        createPrDisabledReason ??
        (implementationSlotClaim ? SLOT_CLAIM_DISABLED_REASON[implementationSlotClaim] : undefined)

    const submit = (note: string): void => {
        if (isCreatingPr || implementationSlotClaim) {
            return
        }
        if (createPrDisabledReason) {
            lemonToast.error(createPrDisabledReason)
            return
        }
        const trimmed = note.trim()
        captureInboxReportAction({
            report,
            actionType: 'create_pr',
            surface: 'detail_pane',
            extra: { has_feedback: trimmed.length > 0 },
        })
        createPrFromReport(report, trimmed || undefined)
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
            onClick={() => submit('')}
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
                    closeOnClickInside: false,
                    overlay: (
                        <div className="flex w-120 flex-col gap-2 p-2">
                            <span className="text-xs font-semibold text-tertiary">
                                Add instructions for the PostHog agent
                            </span>
                            <LemonTextArea
                                value={instructions}
                                onChange={setInstructions}
                                onPressEnter={submit}
                                placeholder="Add instructions for the PostHog agent (optional)"
                                maxLength={4000}
                                rows={4}
                                autoFocus
                                actions={[
                                    <span key="shortcut" className="text-xs text-tertiary">
                                        Enter to implement, Shift + Enter for a new line
                                    </span>,
                                ]}
                            />
                            <div className="flex flex-wrap items-center justify-between gap-2">
                                <LemonButton
                                    type="secondary"
                                    icon={<IconCopy />}
                                    onClick={() => void copyImplementationPrompt()}
                                    data-attr="inbox-report-copy-implementation-prompt"
                                >
                                    Copy prompt for your agent
                                </LemonButton>
                                <LemonButton
                                    type="primary"
                                    icon={<IconPullRequest />}
                                    onClick={() => submit(instructions)}
                                    loading={isCreatingPr}
                                    disabledReason={disabledReason}
                                    data-attr="inbox-report-create-pr-submit"
                                >
                                    Implement with PostHog
                                </LemonButton>
                            </div>
                        </div>
                    ),
                },
            }}
        >
            Implement
        </LemonButton>
    )
}
