import { useActions, useValues } from 'kea'
import { useRef, useState } from 'react'

import { LemonButton, lemonToast } from '@posthog/lemon-ui'

import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'
import { Popover } from 'lib/lemon-ui/Popover'

import { captureInboxReportAction } from '../../inboxAnalytics'
import { inboxTaskKickoffLogic } from '../../inboxTaskKickoffLogic'
import { SignalReport } from '../../types'
import { ReportDetailAction } from './ReportDetailActions'

interface CreatePrReportButtonProps {
    report: SignalReport
    /** Display config for the trigger (icon, label, loading, tooltip, disabledReason). */
    action: ReportDetailAction
    'data-attr'?: string
}

/**
 * The Create PR button as a popover: it opens an optional note the user can leave for the agent
 * before the run starts, then fires the same implementation task. An empty note submits exactly as a
 * plain click did. Rendered standalone rather than as a menu item, since a menu item can't own a
 * popover — the same reason `DiscussReportButton` is standalone.
 */
export function CreatePrReportButton({
    report,
    action,
    'data-attr': dataAttr,
}: CreatePrReportButtonProps): JSX.Element {
    const { isCreatingPr, aiConsentDisabledReason } = useValues(inboxTaskKickoffLogic)
    const { createPrFromReport } = useActions(inboxTaskKickoffLogic)
    const buttonRef = useRef<HTMLButtonElement>(null)
    const [isOpen, setIsOpen] = useState(false)
    const [feedback, setFeedback] = useState('')

    const submit = (): void => {
        const trimmed = feedback.trim()
        // Cmd/Ctrl + Enter submits straight from the textarea, which never sees the button's
        // loading or disabled state. Re-check the guards here, or a second press starts another
        // paid task run for the same report.
        if (isCreatingPr) {
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
            extra: { has_feedback: trimmed.length > 0 },
        })
        // The popover stays open on its spinner until the run is created and we navigate to it, so
        // the request is visibly in flight and a failure leaves the note to retry with.
        createPrFromReport(report, trimmed || undefined)
    }

    return (
        <Popover
            visible={isOpen}
            onClickOutside={(event) => {
                if (event.target instanceof Node && buttonRef.current?.contains(event.target)) {
                    return
                }
                setIsOpen(false)
            }}
            placement="bottom-end"
            overlay={
                <div className="flex flex-col gap-2 p-2 w-[22rem]">
                    <span className="text-xs text-tertiary">
                        Anything the agent should know? Leave a note to steer the PR, or submit without one.
                    </span>
                    <LemonTextArea
                        value={feedback}
                        onChange={setFeedback}
                        onPressCmdEnter={submit}
                        aria-label="Optional direction for the agent"
                        placeholder="e.g. put this behind a feature flag, or skip the migration (optional)"
                        maxLength={4000}
                        rows={4}
                        autoFocus
                        rightFooter={<span className="text-xs text-tertiary">Cmd/Ctrl + Enter to create</span>}
                    />
                    <div className="flex justify-end">
                        <LemonButton
                            type="primary"
                            size="small"
                            onClick={submit}
                            loading={isCreatingPr}
                            data-attr="inbox-report-create-pr-submit"
                        >
                            Create PR
                        </LemonButton>
                    </div>
                </div>
            }
        >
            <LemonButton
                ref={buttonRef}
                type="primary"
                size="small"
                icon={action.icon}
                active={isOpen}
                loading={action.loading}
                tooltip={action.disabledReason ? undefined : action.tooltip}
                disabledReason={action.disabledReason}
                onClick={() => setIsOpen((open) => !open)}
                data-attr={dataAttr}
            >
                {action.label}
            </LemonButton>
        </Popover>
    )
}
