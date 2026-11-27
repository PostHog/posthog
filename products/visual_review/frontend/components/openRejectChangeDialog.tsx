import { LemonTextArea } from '@posthog/lemon-ui'

import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { visualReviewRunsRejectCreateBodySnapshotsItemReasonMax as REJECT_REASON_MAX_LENGTH } from '../generated/api.zod'

export function openRejectChangeDialog(onReject: (reason: string) => void): void {
    // A dialog stays clickable during its close transition, so a double click would send the reject twice.
    let submitted = false
    LemonDialog.openForm({
        title: 'Reject this change?',
        description:
            'Finalize stays blocked until the picture changes or you undo the rejection. ' +
            'Is the old picture the wrong one? Quarantine the story instead.',
        width: 520,
        initialValues: { reason: '' },
        errors: {
            reason: (reason: string) => {
                if (!reason?.trim()) {
                    return 'Say what is wrong, so the author can fix it'
                }
                if (reason.trim().length > REJECT_REASON_MAX_LENGTH) {
                    return `Keep the reason under ${REJECT_REASON_MAX_LENGTH} characters`
                }
                return undefined
            },
        },
        onSubmit: ({ reason }) => {
            if (!submitted) {
                submitted = true
                onReject(reason.trim())
            }
        },
        primaryButtonProps: { children: 'Reject', status: 'danger' },
        content: (
            <LemonField name="reason" label="What is wrong">
                <LemonTextArea
                    autoFocus
                    minRows={3}
                    maxLength={REJECT_REASON_MAX_LENGTH}
                    data-attr="visual-review-reject-reason"
                />
            </LemonField>
        ),
    })
}
