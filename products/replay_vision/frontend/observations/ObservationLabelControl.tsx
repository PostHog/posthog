import { useActions, useValues } from 'kea'

import { IconThumbsDown, IconThumbsDownFilled, IconThumbsUp, IconThumbsUpFilled } from '@posthog/icons'
import { LemonButton, LemonTextArea } from '@posthog/lemon-ui'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { ReplayObservationLabelApi } from '../generated/api.schemas'
import { observationLabelLogic } from './observationLabelLogic'

/**
 * Thumbs up/down rating on whether the scanner got this session right, with feedback on thumbs-down.
 * The rating is shared across the team (one per observation) and gathered later to improve the scanner prompt.
 * `compact` renders just the controls for table cells; the default adds the bordered card and question.
 */
export function ObservationLabelControl({
    observationId,
    initialLabel,
    onChange,
    compact = false,
}: {
    observationId: string
    initialLabel?: ReplayObservationLabelApi | null
    onChange?: (label: ReplayObservationLabelApi | null) => void
    compact?: boolean
}): JSX.Element {
    const logic = observationLabelLogic({ observationId, initialLabel, onChange })
    const { label, saving, feedbackDraft } = useValues(logic)
    const { rate, clearRating, setFeedbackDraft } = useActions(logic)

    const thumbsUp = label?.is_correct === true
    const thumbsDown = label?.is_correct === false
    // Editing the shared rating mutates team-wide data, so it needs edit access (matches the "Edit scanner" gate).
    const editDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.SessionRecording,
        AccessControlLevel.Editor
    )
    const canEdit = !editDisabledReason
    const feedbackSynced = feedbackDraft === (label?.feedback ?? '')

    const buttons = (
        <div className="flex items-center gap-1">
            <LemonButton
                size="xsmall"
                type={thumbsUp ? 'primary' : 'secondary'}
                icon={thumbsUp ? <IconThumbsUpFilled /> : <IconThumbsUp />}
                loading={saving}
                disabledReason={editDisabledReason ?? undefined}
                tooltip="Scanner got this right"
                onClick={() => rate(true, '')}
                data-attr="replay-vision-label-thumbs-up"
            />
            <LemonButton
                size="xsmall"
                type={thumbsDown ? 'primary' : 'secondary'}
                icon={thumbsDown ? <IconThumbsDownFilled /> : <IconThumbsDown />}
                loading={saving}
                disabledReason={editDisabledReason ?? undefined}
                tooltip="Scanner got this wrong. Add feedback to improve the prompt"
                onClick={() => rate(false, feedbackDraft)}
                data-attr="replay-vision-label-thumbs-down"
            />
            {label && canEdit && (
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    onClick={() => clearRating()}
                    disabledReason={saving ? 'Saving…' : undefined}
                >
                    Clear
                </LemonButton>
            )}
        </div>
    )

    const feedback = thumbsDown && (
        <div className="space-y-1">
            <LemonTextArea
                placeholder="What should it have concluded, and why? This feedback is used to improve the prompt."
                value={feedbackDraft}
                onChange={setFeedbackDraft}
                disabled={!canEdit}
                minRows={compact ? 1 : 2}
                data-attr="replay-vision-label-feedback"
            />
            {canEdit && (
                <div className="flex justify-end">
                    <span className="text-xs text-muted" data-attr="replay-vision-label-feedback-status">
                        {saving || !feedbackSynced ? 'Saving…' : 'Saved'}
                    </span>
                </div>
            )}
        </div>
    )

    if (compact) {
        return (
            <div className="space-y-1 py-1">
                {buttons}
                {feedback}
            </div>
        )
    }

    return (
        <div className="border rounded p-3 bg-surface-primary space-y-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-sm font-medium">Did the scanner get this right?</span>
                {buttons}
            </div>
            {feedback}
        </div>
    )
}
