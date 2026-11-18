import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonRadio, LemonRadioOption } from 'lib/lemon-ui/LemonRadio'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'

import { RollbackReasonEnumApi } from './generated/api.schemas'
import { RollbackReasonAnswer } from './rollbackReason'

const REASON_OPTIONS: LemonRadioOption<RollbackReasonEnumApi>[] = [
    { value: RollbackReasonEnumApi.Errors, label: 'Errors or bugs' },
    { value: RollbackReasonEnumApi.Metrics, label: 'Metrics got worse' },
    { value: RollbackReasonEnumApi.Planned, label: 'It was planned' },
    { value: RollbackReasonEnumApi.WrongConfiguration, label: 'Wrong configuration' },
    { value: RollbackReasonEnumApi.Other, label: 'Other' },
]

interface OpenRollbackReasonDialogParams {
    /** Called with the reason, or with `'skipped'`, when the person chooses to save. */
    onAnswer: (answer: RollbackReasonAnswer) => void
    /** Called when the dialog closes without an answer. The edit is not saved. */
    onCancel: () => void
}

export function openRollbackReasonDialog({ onAnswer, onCancel }: OpenRollbackReasonDialogParams): void {
    let answered = false
    const answer = (value: RollbackReasonAnswer): void => {
        if (answered) {
            return
        }
        answered = true
        onAnswer(value)
    }
    const primaryButtonProps = { children: 'Save', 'data-attr': 'feature-flag-rollback-reason-save' }

    LemonDialog.openForm({
        title: 'Why are you rolling back this flag?',
        description: "Fewer people get this flag after this change. Your answer is saved in the flag's history.",
        maxWidth: '32rem',
        initialValues: { reason: null as RollbackReasonEnumApi | null, note: '' },
        content: (
            <div className="flex flex-col gap-3">
                <LemonField name="reason" label="Reason">
                    {({ value, onChange }) => (
                        <LemonRadio aria-label="Reason" value={value} onChange={onChange} options={REASON_OPTIONS} />
                    )}
                </LemonField>
                <LemonField name="note" label="Note" showOptional>
                    <LemonTextArea
                        // Enter in this multi-line note must not submit the dialog form. Escape still closes it.
                        onKeyDown={(e) => e.key === 'Enter' && e.stopPropagation()}
                        maxLength={1000}
                        minRows={2}
                        maxRows={6}
                    />
                </LemonField>
            </div>
        ),
        errors: {
            reason: (reason) => (!reason ? 'Pick a reason, or skip the question' : undefined),
        },
        primaryButtonProps,
        tertiaryButton: {
            children: 'Skip and save',
            'data-attr': 'feature-flag-rollback-reason-skip',
            onClick: () => answer('skipped'),
        },
        onSubmit: ({ reason, note }) => {
            if (reason) {
                answer({ reason, note: (note ?? '').trim() })
            }
        },
        onAfterClose: () => {
            if (!answered) {
                onCancel()
            }
        },
    })
}
