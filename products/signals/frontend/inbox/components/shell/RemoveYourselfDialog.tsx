import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'

import type { ReviewerRemovalReasonEnumApi } from 'products/signals/frontend/generated/api.schemas'

import { reviewerRemovalReasonOptions } from '../../utils/reviewerRemovalReasons'
import { HotkeyRadio } from './HotkeyRadio'

const WITHOUT_A_REASON = 'none'
type RemoveYourselfChoice = ReviewerRemovalReasonEnumApi | typeof WITHOUT_A_REASON

/**
 * Asks why you step off the current report in triage, where every action is keyboard driven: a digit
 * picks the reason and Enter confirms, the same way the triage dismiss dialog works.
 */
export function openRemoveYourselfDialog({
    reportTitle,
    onConfirm,
}: {
    reportTitle: string
    onConfirm: (reason: ReviewerRemovalReasonEnumApi | undefined) => void
}): void {
    const options = [
        ...reviewerRemovalReasonOptions(true),
        { value: WITHOUT_A_REASON as RemoveYourselfChoice, label: 'Without a reason' },
    ]
    const primaryButtonProps = { children: 'Remove yourself', 'data-attr': 'inbox-triage-remove-yourself-submit' }
    LemonDialog.openForm({
        title: `Remove yourself from "${reportTitle}"?`,
        description: 'The report stays open for its other reviewers.',
        maxWidth: '32rem',
        overlayClassName: '!items-center',
        initialValues: { reason: null as RemoveYourselfChoice | null },
        content: (
            <LemonField name="reason" label="Reason">
                {({ value, onChange }) => <HotkeyRadio value={value} onChange={onChange} options={options} />}
            </LemonField>
        ),
        errors: {
            reason: (reason) => (!reason ? "You haven't picked an option" : undefined),
        },
        primaryButtonProps,
        onSubmit: ({ reason }) => onConfirm(reason && reason !== WITHOUT_A_REASON ? reason : undefined),
    })
}
