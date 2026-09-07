import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonRadio, LemonRadioOption } from 'lib/lemon-ui/LemonRadio'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'

import { RESOLVE_REASON_OPTIONS, ResolveReasonValue } from '../../utils/dismissalReasons'
import { HotkeyRadio } from './HotkeyRadio'

export interface ResolveReportDialogResult {
    reason: ResolveReasonValue
    note: string
}

interface OpenResolveReportDialogParams {
    /** Report title for single-report copy. Ignored when `selectedCount > 1`. */
    reportTitle?: string | null
    /** When greater than 1, copy reflects a bulk resolve of the current selection. */
    selectedCount?: number
    /** Whether the report has an implementation PR that is still open. Resolving closes it, so the copy says so. */
    hasOpenPr?: boolean
    /** Show a digit keycap on each reason and let 1..9 pick it. On for triage mode, where the whole flow is keyboard-driven. */
    hotkeys?: boolean
    /** Preselect this reason. The context menu's "Something else…" opens the dialog with it set,
     * so the person only has to write the note. */
    initialReason?: ResolveReasonValue
    /** Called with the chosen reason + note once the user confirms. */
    onConfirm: (result: ResolveReportDialogResult) => void | Promise<void>
}

const REASON_RADIO_OPTIONS: LemonRadioOption<ResolveReasonValue>[] = RESOLVE_REASON_OPTIONS.map((option) => ({
    value: option.value,
    label: option.label,
}))

/**
 * Opens the resolve dialog: pick why the report is done (canonical {@link RESOLVE_REASON_OPTIONS})
 * plus an optional note, then mark it resolved with Enter or the button. Same shape as
 * {@link openDismissReportDialog}, so the two verdicts read alike. The caller wires `onConfirm` to
 * the bulk-resolve action or a direct
 * `api.signalReports.setState(id, { state: 'resolved', dismissal_reason, dismissal_note })`.
 */
export function openResolveReportDialog({
    reportTitle,
    selectedCount = 1,
    hasOpenPr = false,
    hotkeys = false,
    initialReason,
    onConfirm,
}: OpenResolveReportDialogParams): void {
    const isBulk = selectedCount > 1
    const title = isBulk
        ? `Resolve ${selectedCount} reports?`
        : `Resolve report "${reportTitle?.trim() ? reportTitle : 'Untitled report'}"?`
    const description = isBulk
        ? 'These reports are marked as done. If an issue comes back, you get a new report linked to the old one. Any open pull request for these reports is closed.'
        : `This marks the report as done. If the issue comes back, you get a new report linked to this one.${
              hasOpenPr ? ' The pull request opened for this report is closed.' : ''
          }`

    LemonDialog.openForm({
        title,
        description,
        maxWidth: '36rem',
        overlayClassName: '!items-center',
        initialValues: { reason: initialReason ?? null, note: '' },
        content: (
            <div className="flex flex-col gap-3">
                <LemonField name="reason" label="Reason">
                    {({ value, onChange }) =>
                        hotkeys ? (
                            <HotkeyRadio value={value} onChange={onChange} options={RESOLVE_REASON_OPTIONS} />
                        ) : (
                            <LemonRadio value={value} onChange={onChange} options={REASON_RADIO_OPTIONS} />
                        )
                    }
                </LemonField>
                <LemonField
                    name="note"
                    label="Note"
                    info="Optional. A link to the fix helps anyone who reads this report later."
                >
                    <LemonTextArea
                        // stopPropagation keeps Enter in this multi-line note from reaching the dialog
                        // form and resolving the report (and closing its PR) mid-sentence.
                        stopPropagation
                        // With the reason already chosen, the note is the only thing left to type.
                        // Never focus otherwise: the hotkey flow reads digits as reason picks.
                        autoFocus={initialReason != null}
                        placeholder="Link to the pull request or commit, or what fixed it."
                        maxLength={4000}
                        minRows={3}
                        maxRows={8}
                    />
                </LemonField>
            </div>
        ),
        errors: {
            reason: (reason) => (!reason ? "You haven't picked a reason" : undefined),
        },
        primaryButtonProps: { children: isBulk ? 'Resolve reports' : 'Resolve report' },
        shouldAwaitSubmit: true,
        onSubmit: async ({ reason, note }) => {
            if (!reason) {
                return
            }
            await onConfirm({ reason, note: (note ?? '').trim() })
        },
    })
}
