import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonRadio, LemonRadioOption } from 'lib/lemon-ui/LemonRadio'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'

import { DISMISSAL_REASON_OPTIONS, DismissalReasonValue } from '../../utils/dismissalReasons'
import { HotkeyRadio } from './HotkeyRadio'

export interface DismissReportDialogResult {
    reason: DismissalReasonValue
    note: string
}

interface OpenDismissReportDialogParams {
    /** Report title for single-report copy. Ignored when `selectedCount > 1`. */
    reportTitle?: string | null
    /** When greater than 1, copy reflects a bulk dismiss of the current selection. */
    selectedCount?: number
    /** Show a digit keycap on each reason and let 1..9 pick it. On for triage mode, where the whole flow is keyboard-driven. */
    hotkeys?: boolean
    /** Called with the chosen reason + note once the user confirms. */
    onConfirm: (result: DismissReportDialogResult) => void | Promise<void>
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
    hotkeys = false,
    onConfirm,
}: OpenDismissReportDialogParams): void {
    const isBulk = selectedCount > 1
    const title = isBulk
        ? `Dismiss ${selectedCount} reports?`
        : `Dismiss report "${reportTitle?.trim() ? reportTitle : 'Untitled report'}"?`
    const description = isBulk
        ? 'These reports leave your inbox. Your feedback is saved on each report, and your note goes to the agents that filed them.'
        : 'This report leaves your inbox. Your feedback is saved on the report, and your note goes to the agent that filed it.'

    LemonDialog.openForm({
        title,
        description,
        maxWidth: '36rem',
        overlayClassName: '!items-center',
        initialValues: { reason: null as DismissalReasonValue | null, note: '' },
        content: (
            <div className="flex flex-col gap-3">
                <LemonField name="reason" label="Reason">
                    {({ value, onChange }) =>
                        hotkeys ? (
                            <HotkeyRadio value={value} onChange={onChange} options={DISMISSAL_REASON_OPTIONS} />
                        ) : (
                            <LemonRadio value={value} onChange={onChange} options={REASON_RADIO_OPTIONS} />
                        )
                    }
                </LemonField>
                <LemonField name="note" label="Note" info="Optional. The agent reads it on its next run.">
                    <LemonTextArea
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
        onSubmit: async ({ reason, note }) => {
            if (!reason) {
                return
            }
            await onConfirm({ reason, note: (note ?? '').trim() })
        },
    })
}
