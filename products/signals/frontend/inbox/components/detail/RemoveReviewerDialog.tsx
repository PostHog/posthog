import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonRadio, LemonRadioOption } from 'lib/lemon-ui/LemonRadio'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'

import type { ReviewerRemovalReasonEnumApi } from 'products/signals/frontend/generated/api.schemas'

import { ReviewerRemoval } from '../../types'

interface OpenRemoveReviewerDialogParams {
    reviewerName: string
    /** The person removes themselves, so the copy speaks to them instead of about a teammate. */
    isSelf: boolean
    onConfirm: (removal: ReviewerRemoval) => void
}

function reasonOptions(isSelf: boolean): LemonRadioOption<ReviewerRemovalReasonEnumApi>[] {
    return [
        { value: 'wrong_area', label: isSelf ? "This isn't my area" : "This isn't their area" },
        { value: 'owned_by_someone_else', label: 'Someone else owns this' },
        { value: 'unavailable', label: isSelf ? "I'm not available right now" : "They're not available right now" },
        { value: 'other', label: 'Something else' },
    ]
}

/**
 * Asks why a reviewer is removed before the removal is saved. Both fields are optional, so a person
 * can still remove someone in one extra click. The reason reaches research and the scouts, which
 * read it when they pick reviewers for later reports.
 */
export function openRemoveReviewerDialog({ reviewerName, isSelf, onConfirm }: OpenRemoveReviewerDialogParams): void {
    const primaryButtonProps = { children: 'Remove', 'data-attr': 'inbox-remove-reviewer-submit' }
    LemonDialog.openForm({
        title: isSelf ? 'Remove yourself from this report?' : `Remove ${reviewerName} from this report?`,
        description: 'The report stays open. A reason helps the agent pick better reviewers for similar reports.',
        maxWidth: '32rem',
        overlayClassName: '!items-center',
        initialValues: { reason: null as ReviewerRemovalReasonEnumApi | null, note: '' },
        content: (
            <div className="flex flex-col gap-3">
                <LemonField name="reason" label="Reason" info="Optional.">
                    {({ value, onChange }) => (
                        <LemonRadio value={value} onChange={onChange} options={reasonOptions(isSelf)} />
                    )}
                </LemonField>
                <LemonField name="note" label="Note" info="Optional. Name the area, so the agent knows what to skip.">
                    <LemonTextArea
                        // stopPropagation keeps Enter in this multi-line note from submitting the dialog.
                        stopPropagation
                        placeholder="For example: I work on billing, not checkout."
                        maxLength={500}
                        minRows={2}
                        maxRows={6}
                    />
                </LemonField>
            </div>
        ),
        errors: {},
        primaryButtonProps,
        onSubmit: ({ reason, note }) => onConfirm({ reason: reason ?? null, note: note ?? '' }),
    })
}
