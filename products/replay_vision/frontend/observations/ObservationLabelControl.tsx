import { useActions, useValues } from 'kea'

import { IconThumbsDown, IconThumbsDownFilled, IconThumbsUp, IconThumbsUpFilled } from '@posthog/icons'
import { LemonButton, LemonTextArea } from '@posthog/lemon-ui'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { replayObservationLogic } from './replayObservationLogic'

/**
 * Lets an editor mark whether the scanner scored this session correctly and, when wrong, leave feedback.
 * The label is shared across the team (one per observation) and gathered later to improve the scanner prompt.
 */
export function ObservationLabelControl({ observationId }: { observationId: string }): JSX.Element {
    const logic = replayObservationLogic({ id: observationId })
    const { observation, labelSaving, feedbackDraft } = useValues(logic)
    const { setLabel, clearLabel, setFeedbackDraft } = useActions(logic)

    const label = observation?.label ?? null
    const labeledIncorrect = label?.is_correct === false
    // Editing the shared label mutates team-wide data, so it needs edit access (matches the "Edit scanner" gate).
    const editDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.SessionRecording,
        AccessControlLevel.Editor
    )
    const canEdit = !editDisabledReason
    const feedbackSynced = feedbackDraft === (label?.feedback ?? '')

    return (
        <div className="border rounded p-3 bg-surface-primary space-y-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-sm font-medium">Did the scanner get this right?</span>
                <div className="flex items-center gap-1">
                    <LemonButton
                        size="xsmall"
                        type={label?.is_correct === true ? 'primary' : 'secondary'}
                        icon={label?.is_correct === true ? <IconThumbsUpFilled /> : <IconThumbsUp />}
                        loading={labelSaving}
                        disabledReason={editDisabledReason ?? undefined}
                        tooltip="Scanner got this right"
                        onClick={() => setLabel(true, '')}
                        data-attr="replay-vision-label-thumbs-up"
                    />
                    <LemonButton
                        size="xsmall"
                        type={labeledIncorrect ? 'primary' : 'secondary'}
                        icon={labeledIncorrect ? <IconThumbsDownFilled /> : <IconThumbsDown />}
                        loading={labelSaving}
                        disabledReason={editDisabledReason ?? undefined}
                        tooltip="Scanner got this wrong. Add feedback to improve the prompt"
                        onClick={() => setLabel(false, feedbackDraft)}
                        data-attr="replay-vision-label-thumbs-down"
                    />
                    {label && canEdit && (
                        <LemonButton
                            size="xsmall"
                            type="tertiary"
                            onClick={() => clearLabel()}
                            disabledReason={labelSaving ? 'Saving…' : undefined}
                        >
                            Clear
                        </LemonButton>
                    )}
                </div>
            </div>
            {labeledIncorrect && (
                <div className="space-y-1">
                    <LemonTextArea
                        placeholder="What should it have concluded, and why? This feedback is used to improve the prompt."
                        value={feedbackDraft}
                        onChange={setFeedbackDraft}
                        disabled={!canEdit}
                        minRows={2}
                        data-attr="replay-vision-label-feedback"
                    />
                    {canEdit && (
                        <div className="flex justify-end">
                            <span className="text-xs text-muted" data-attr="replay-vision-label-feedback-status">
                                {labelSaving || !feedbackSynced ? 'Saving…' : 'Saved'}
                            </span>
                        </div>
                    )}
                </div>
            )}
        </div>
    )
}
