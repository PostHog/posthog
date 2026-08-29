import { useActions, useValues } from 'kea'
import { useRef, useState } from 'react'

import { IconChevronDown, IconPullRequest } from '@posthog/icons'
import { LemonButton, lemonToast } from '@posthog/lemon-ui'

import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'
import { Popover } from 'lib/lemon-ui/Popover'

import { captureInboxReportAction } from '../../inboxAnalytics'
import { inboxTaskKickoffLogic } from '../../inboxTaskKickoffLogic'
import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { SignalReport } from '../../types'

// Same string desktop uses, so the note reads the same on both surfaces.
const PLACEHOLDER = 'Add direction for the agent (optional)…'

/**
 * The detail-pane "Create PR" action. It opens a popover with an optional note instead of firing on
 * click, so the reader can steer the agent (behind a flag, backend only, skip the migration) at the
 * moment they have the most context. An empty note behaves exactly as the old fire-on-click button.
 *
 * A component, not a `ReportDetailAction`, because actions collapse into a `LemonMenu` on narrow
 * layouts and a menu item can't own a popover — this mirrors `DiscussReportButton` for the same reason.
 */
export function CreatePrButton({ report }: { report: SignalReport }): JSX.Element {
    const { isCreatingPr, aiConsentDisabledReason } = useValues(inboxTaskKickoffLogic)
    // Already mounted by `ReportDetail`, so this reads the loaded value rather than starting a fetch.
    const { hasLiveImplementationTask } = useValues(inboxReportDetailLogic({ reportId: report.id, report }))
    const { createPrFromReport } = useActions(inboxTaskKickoffLogic)
    const buttonRef = useRef<HTMLButtonElement>(null)
    const [isOpen, setIsOpen] = useState(false)
    const [feedback, setFeedback] = useState('')

    const disabledReason =
        aiConsentDisabledReason ??
        (hasLiveImplementationTask
            ? 'A PR task already exists for this report. Open it in the task log to continue.'
            : undefined)

    const submit = (): void => {
        // Cmd/Ctrl + Enter submits straight from the textarea, so it never sees the trigger's
        // `disabledReason` — each guard has to hold here too, or a press fires a paid run anyway.
        if (isCreatingPr || hasLiveImplementationTask) {
            return
        }
        if (aiConsentDisabledReason) {
            lemonToast.error(aiConsentDisabledReason)
            return
        }
        const trimmed = feedback.trim()
        captureInboxReportAction({
            report,
            actionType: 'create_pr',
            surface: 'detail_pane',
            extra: { has_feedback: trimmed.length > 0 },
        })
        // The popover stays open on its spinner until the run is created and we navigate to it, so a
        // failure leaves the note to retry with.
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
                    <LemonTextArea
                        value={feedback}
                        onChange={setFeedback}
                        onPressCmdEnter={submit}
                        placeholder={PLACEHOLDER}
                        maxLength={4000}
                        rows={4}
                        autoFocus
                        rightFooter={<span className="text-xs text-tertiary">Cmd/Ctrl + Enter to create PR</span>}
                    />
                    <div className="flex justify-end">
                        <LemonButton
                            type="primary"
                            size="small"
                            icon={<IconPullRequest />}
                            onClick={submit}
                            loading={isCreatingPr}
                            disabledReason={disabledReason}
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
                icon={<IconPullRequest />}
                // Keeps the chevron the plain button never had, so a returning reader sees it now
                // opens a note box before it fires.
                sideIcon={<IconChevronDown />}
                active={isOpen}
                loading={isCreatingPr}
                // The trigger always opens, even when consent is missing or a PR task already exists;
                // the reason sits on the submit inside, next to the thing it blocks.
                tooltip="Have Self-driving open a pull request for this report"
                onClick={() => setIsOpen((open) => !open)}
                data-attr="inbox-report-create-pr"
            >
                Create PR
            </LemonButton>
        </Popover>
    )
}
