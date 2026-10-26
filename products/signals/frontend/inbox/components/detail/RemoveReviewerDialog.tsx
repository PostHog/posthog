import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonRadio, LemonRadioOption } from 'lib/lemon-ui/LemonRadio'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'

import type { ReviewerRemovalReasonEnumApi } from 'products/signals/frontend/generated/api.schemas'

import { ReviewerRemoval } from '../../types'
import { ReviewerExclusionArea, reviewerExclusionAreaLabel } from '../../utils/reviewerExclusionAreas'

interface OpenRemoveReviewerDialogParams {
    reviewerName: string
    /** The person removes themselves, so the copy speaks to them instead of about a teammate. */
    isSelf: boolean
    /** Areas the person can stay off from now on. Offered only when they remove themselves. */
    exclusionAreas?: ReviewerExclusionArea[]
    onConfirm: (removal: ReviewerRemoval, stayOff: ReviewerExclusionArea | null) => void
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
export function openRemoveReviewerDialog({
    reviewerName,
    isSelf,
    exclusionAreas = [],
    onConfirm,
}: OpenRemoveReviewerDialogParams): void {
    const areas = isSelf ? exclusionAreas : []
    const primaryButtonProps = { children: 'Remove', 'data-attr': 'inbox-remove-reviewer-submit' }
    LemonDialog.openForm({
        title: isSelf ? 'Remove yourself from this report?' : `Remove ${reviewerName} from this report?`,
        description: 'The report stays open. A reason helps the agent pick better reviewers for similar reports.',
        maxWidth: '32rem',
        overlayClassName: '!items-center',
        initialValues: {
            reason: null as ReviewerRemovalReasonEnumApi | null,
            note: '',
            stayOff: null as number | null,
        },
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
                {areas.length > 0 && (
                    <LemonField
                        name="stayOff"
                        label="Stay off this area"
                        info="Optional. Automatic reviewer picks skip you for later reports in this area. You can undo it in your inbox settings."
                    >
                        {({ value, onChange }) => (
                            <LemonSelect
                                fullWidth
                                value={value}
                                onChange={onChange}
                                options={[
                                    { value: null, label: "Don't add a standing rule" },
                                    ...areas.map((area, index) => ({
                                        value: index,
                                        label: reviewerExclusionAreaLabel(area),
                                    })),
                                ]}
                                data-attr="inbox-remove-reviewer-stay-off"
                            />
                        )}
                    </LemonField>
                )}
            </div>
        ),
        errors: {},
        primaryButtonProps,
        onSubmit: ({ reason, note, stayOff }) =>
            onConfirm({ reason: reason ?? null, note: note ?? '' }, stayOff != null ? (areas[stayOff] ?? null) : null),
    })
}
