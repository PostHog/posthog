import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconPullRequest } from '@posthog/icons'
import { LemonButton, lemonToast } from '@posthog/lemon-ui'

import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'

import { captureInboxReportAction } from '../../inboxAnalytics'
import { inboxTaskKickoffLogic } from '../../inboxTaskKickoffLogic'
import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { SignalReport } from '../../types'

// Same string desktop uses, so the note reads the same on both surfaces.
const PLACEHOLDER = 'Add direction for the agent (optional)…'

/**
 * The detail-pane "Create PR" action, as a split button.
 *
 * The main half starts the run immediately, because an unsteered run is the common case. The
 * chevron half opens a note box, so the reader can steer the agent (behind a flag, backend only,
 * skip the migration) at the moment they have the most context. A note is optional, so both halves
 * reach the same action and only the note differs.
 *
 * A component, not a `ReportDetailAction`, because actions collapse into a `LemonMenu` on narrow
 * layouts and a menu item cannot own a popover. `DiscussReportButton` is a component for the same
 * reason.
 */
export function CreatePrButton({ report }: { report: SignalReport }): JSX.Element {
    const { isCreatingPr, aiConsentDisabledReason } = useValues(inboxTaskKickoffLogic)
    // Already mounted by `ReportDetail`, so this reads the loaded value rather than starting a fetch.
    const { hasLiveImplementationTask } = useValues(inboxReportDetailLogic({ reportId: report.id, report }))
    const { createPrFromReport } = useActions(inboxTaskKickoffLogic)
    const [feedback, setFeedback] = useState('')

    const disabledReason =
        aiConsentDisabledReason ??
        (hasLiveImplementationTask
            ? 'A PR task already exists for this report. Open it in the task log to continue.'
            : undefined)

    const submit = (note: string): void => {
        // Enter submits straight from the textarea, so it never sees the button's `disabledReason`.
        // Each guard has to hold here too, or a keypress starts a paid run anyway.
        if (isCreatingPr || hasLiveImplementationTask) {
            return
        }
        if (aiConsentDisabledReason) {
            lemonToast.error(aiConsentDisabledReason)
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

    return (
        <LemonButton
            type="primary"
            size="small"
            icon={<IconPullRequest />}
            onClick={() => submit('')}
            loading={isCreatingPr}
            disabledReason={disabledReason}
            tooltip="Have Self-driving open a pull request for this report"
            data-attr="inbox-report-create-pr"
            sideAction={{
                tooltip: 'Add direction before the agent starts',
                'aria-label': 'Add direction for the agent',
                'data-attr': 'inbox-report-create-pr-steer',
                dropdown: {
                    placement: 'bottom-end',
                    // The box holds a textarea, so a click inside it must not close the popover. The
                    // popover also stays open on its spinner until the run is created and we navigate
                    // to it, which leaves the note to retry with after a failure.
                    closeOnClickInside: false,
                    overlay: (
                        <div className="flex flex-col gap-2 p-2 w-96">
                            <LemonTextArea
                                value={feedback}
                                onChange={setFeedback}
                                onPressEnter={submit}
                                placeholder={PLACEHOLDER}
                                maxLength={4000}
                                rows={4}
                                autoFocus
                                // The hint goes in the left slot so the character counter, which
                                // `maxLength` puts in the right one, has room of its own.
                                actions={[
                                    <span key="shortcut" className="text-xs text-tertiary">
                                        Enter to create PR, Shift + Enter for a new line
                                    </span>,
                                ]}
                            />
                            <div className="flex justify-end">
                                <LemonButton
                                    type="primary"
                                    size="small"
                                    icon={<IconPullRequest />}
                                    onClick={() => submit(feedback)}
                                    loading={isCreatingPr}
                                    disabledReason={disabledReason}
                                    data-attr="inbox-report-create-pr-submit"
                                >
                                    Create PR
                                </LemonButton>
                            </div>
                        </div>
                    ),
                },
            }}
        >
            Create PR
        </LemonButton>
    )
}
