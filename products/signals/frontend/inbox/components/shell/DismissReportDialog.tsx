import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonRadio, LemonRadioOption } from 'lib/lemon-ui/LemonRadio'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'

import { DISMISSAL_REASON_OPTIONS, DismissalFeedback, DismissalReasonValue } from '../../utils/dismissalReasons'
import { DismissCorrectedRepoField } from './DismissCorrectedRepoField'
import { HotkeyRadio } from './HotkeyRadio'

interface OpenDismissReportDialogParams {
    /** Report title for single-report copy. Ignored when `selectedCount > 1`. */
    reportTitle?: string | null
    /** When greater than 1, copy reflects a bulk dismiss of the current selection. */
    selectedCount?: number
    /** Whether the report has an implementation PR that is still open. Dismissing closes it, so the copy says so. */
    hasOpenPr?: boolean
    /** Show a digit keycap on each reason and let 1..9 pick it. On for triage mode, where the whole flow is keyboard-driven. */
    hotkeys?: boolean
    /** Preselect this reason. The context menu's "Something else…" opens the dialog with it set,
     * so the person only has to write the note. */
    initialReason?: DismissalReasonValue
    /** Called with the chosen reason, note and optional repo correction once the user confirms. */
    onConfirm: (result: DismissalFeedback) => void | Promise<void>
}

const REASON_RADIO_OPTIONS: LemonRadioOption<DismissalReasonValue>[] = DISMISSAL_REASON_OPTIONS.map((option) => ({
    value: option.value,
    label: option.label,
}))

/**
 * Opens the dismiss dialog. Mirrors desktop `DismissReportDialog`: pick a reason
 * (canonical {@link DISMISSAL_REASON_OPTIONS}) plus an optional note, then suppress.
 * The caller wires `onConfirm` to the bulk-dismiss action or a direct
 * `api.signalReports.setState(id, { state: 'suppressed', dismissal_reason, dismissal_note })`.
 * Its sibling {@link openResolveReportDialog} has the same shape for the other verdict.
 */
export function openDismissReportDialog({
    reportTitle,
    selectedCount = 1,
    hasOpenPr = false,
    hotkeys = false,
    initialReason,
    onConfirm,
}: OpenDismissReportDialogParams): void {
    const isBulk = selectedCount > 1
    const title = isBulk
        ? `Dismiss ${selectedCount} reports?`
        : `Dismiss report "${reportTitle?.trim() ? reportTitle : 'Untitled report'}"?`
    const description = isBulk
        ? `These reports leave your inbox. Your feedback is saved on each report, and your note goes to the agents that filed them.${
              hasOpenPr ? ' Any open pull request for these reports is closed.' : ''
          }`
        : `This report leaves your inbox. Your feedback is saved on the report, and your note goes to the agent that filed it.${
              hasOpenPr ? ' The pull request opened for this report is closed.' : ''
          }`

    LemonDialog.openForm({
        title,
        description,
        maxWidth: '36rem',
        overlayClassName: '!items-center',
        initialValues: {
            reason: (initialReason ?? null) as DismissalReasonValue | null,
            note: '',
            correctedRepository: null as string | null,
        },
        content: (
            <div className="flex flex-col gap-3">
                <LemonField name="reason" label="Reason">
                    {({ value, onChange }) => (
                        <div className="flex flex-col gap-3">
                            {hotkeys ? (
                                <HotkeyRadio value={value} onChange={onChange} options={DISMISSAL_REASON_OPTIONS} />
                            ) : (
                                <LemonRadio value={value} onChange={onChange} options={REASON_RADIO_OPTIONS} />
                            )}
                            {value === 'wrong_repo' && <DismissCorrectedRepoField />}
                        </div>
                    )}
                </LemonField>
                <LemonField name="note" label="Note" info="Optional. The agent reads it on its next run.">
                    <LemonTextArea
                        // stopPropagation keeps Enter in this multi-line note from reaching the dialog
                        // form and dismissing the report (and closing its PR) mid-sentence.
                        stopPropagation
                        // With the reason already chosen, the note is the only thing left to type.
                        // Never focus otherwise: the hotkey flow reads digits as reason picks.
                        autoFocus={initialReason != null}
                        placeholder="What made this report wrong, or not worth fixing?"
                        maxLength={4000}
                        minRows={5}
                        maxRows={12}
                    />
                </LemonField>
            </div>
        ),
        errors: {
            reason: (reason) => (!reason ? "You haven't picked a reason" : undefined),
        },
        primaryButtonProps: { children: 'Dismiss & teach the agent' },
        shouldAwaitSubmit: true,
        onSubmit: async ({ reason, note, correctedRepository }) => {
            if (!reason) {
                return
            }
            await onConfirm({
                reason,
                note: (note ?? '').trim(),
                // A correction picked and then abandoned for another reason must not ride along.
                correctedRepository: reason === 'wrong_repo' ? (correctedRepository ?? null) : null,
            })
        },
    })
}
