import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconThumbsDown, IconThumbsDownFilled, IconThumbsUp, IconThumbsUpFilled } from '@posthog/icons'
import { LemonButton, LemonTextArea, Popover, Tooltip } from '@posthog/lemon-ui'

import { KeyboardShortcut } from 'lib/components/KeyboardShortcut/KeyboardShortcut'
import { FEATURE_FLAGS } from 'lib/constants'
import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { AccessControlLevel } from '~/types'

import type { ReplayObservationLabelApi } from '../generated/api.schemas'
import { getReplayVisionEditDisabledReason } from '../utils/accessControl'
import { observationLabelLogic } from './observationLabelLogic'

export interface ObservationLabelProps {
    observationId: string
    initialLabel?: ReplayObservationLabelApi | null
    onChange?: (label: ReplayObservationLabelApi | null) => void
    /** The observation's scanner's effective access level, for object-level overrides. Falls back to the
     * resource default when the caller doesn't have the scanner loaded. */
    scannerUserAccessLevel?: AccessControlLevel | null
}

const FEEDBACK_PLACEHOLDER =
    'Optional: what did it get right or wrong, and why? Used to improve the scanner configuration.'
// Asked on a thumbs down only, where naming the right answer is what a recommendation can act on.
const WRONG_ANSWER_PLACEHOLDER =
    'What should it have concluded? One line is enough, and it shapes the next recommendation.'

function useEditAccess(scannerUserAccessLevel?: AccessControlLevel | null): string | null {
    // Editing the shared rating mutates team-wide data derived from a recording, so it needs the same
    // bar as the backend label write: replay_scanner editor AND session_recording viewer.
    return getReplayVisionEditDisabledReason(scannerUserAccessLevel)
}

function FeedbackEditor({
    observationId,
    initialLabel,
    onChange,
    scannerUserAccessLevel,
    compact,
    onBlur,
    promptForRightAnswer = false,
}: ObservationLabelProps & { compact: boolean; onBlur?: () => void; promptForRightAnswer?: boolean }): JSX.Element {
    const logic = observationLabelLogic({ observationId, initialLabel, onChange })
    const { saving, saveFailed, feedbackDraft, feedbackSynced } = useValues(logic)
    const { setFeedbackDraft } = useActions(logic)
    const canEdit = !useEditAccess(scannerUserAccessLevel)

    return (
        <div className="space-y-1">
            <LemonTextArea
                placeholder={promptForRightAnswer ? WRONG_ANSWER_PLACEHOLDER : FEEDBACK_PLACEHOLDER}
                value={feedbackDraft}
                onChange={setFeedbackDraft}
                disabled={!canEdit}
                minRows={compact ? 1 : 2}
                autoFocus={compact}
                onBlur={onBlur}
                data-attr="replay-vision-label-feedback"
            />
            {canEdit && (
                <div className="flex justify-end">
                    <span
                        className={`text-xs ${saveFailed ? 'text-danger' : 'text-muted'}`}
                        data-attr="replay-vision-label-feedback-status"
                    >
                        {saveFailed ? 'Not saved' : saving || !feedbackSynced ? 'Saving…' : 'Saved'}
                    </span>
                </div>
            )}
        </div>
    )
}

/**
 * Feedback cell for the calibration table: optional written context on a rated observation (thumbs up or down).
 * Collapses to a truncated one-liner until clicked, so only the row being edited grows. Unrated rows
 * show a hint to rate first, since feedback lives on the shared label.
 */
export function ObservationLabelFeedback({
    observationId,
    initialLabel,
    onChange,
    scannerUserAccessLevel,
}: ObservationLabelProps): JSX.Element {
    const logic = observationLabelLogic({ observationId, initialLabel, onChange })
    const { label, feedbackDraft } = useValues(logic)
    const [editing, setEditing] = useState(false)
    const canEdit = !useEditAccess(scannerUserAccessLevel)

    if (!label) {
        return (
            <Tooltip title="Rate the result first, then add optional feedback">
                <span className="text-muted">—</span>
            </Tooltip>
        )
    }

    if (!editing) {
        return (
            <div
                className={`text-xs truncate ${feedbackDraft ? 'text-muted' : 'text-muted italic'} ${
                    canEdit ? 'cursor-pointer hover:text-default' : ''
                }`}
                onClick={canEdit ? () => setEditing(true) : undefined}
                title={canEdit ? 'Click to edit feedback' : undefined}
                data-attr="replay-vision-label-feedback-collapsed"
            >
                {feedbackDraft || 'Add feedback…'}
            </div>
        )
    }

    // The pending autosave still fires after collapsing on blur.
    return (
        <FeedbackEditor
            observationId={observationId}
            initialLabel={initialLabel}
            onChange={onChange}
            scannerUserAccessLevel={scannerUserAccessLevel}
            compact
            onBlur={() => setEditing(false)}
        />
    )
}

/**
 * Thumbs up/down rating on whether the scanner got this session right. The rating is shared across the
 * team (one per observation) and gathered later to improve the scanner prompt. `compact` renders just the
 * buttons for table cells (feedback lives in its own column via `ObservationLabelFeedback`); the default
 * adds the question, opens the optional feedback editor in a popover after a rating, and hides once rated.
 */
export function ObservationLabelControl({
    observationId,
    initialLabel,
    onChange,
    scannerUserAccessLevel,
    compact = false,
}: ObservationLabelProps & { compact?: boolean }): JSX.Element {
    const logic = observationLabelLogic({ observationId, initialLabel, onChange })
    const { label, saving, feedbackDraft } = useValues(logic)
    const { rate, clearRating } = useActions(logic)
    const { featureFlags } = useValues(featureFlagLogic)
    const [feedbackOpen, setFeedbackOpen] = useState(false)

    const thumbsUp = label?.is_correct === true
    const thumbsDown = label?.is_correct === false
    const editDisabledReason = useEditAccess(scannerUserAccessLevel)

    // Clicking the active thumb again removes the rating.
    const onThumb = (isCorrect: boolean): void => {
        if (label?.is_correct === isCorrect) {
            clearRating()
            setFeedbackOpen(false)
            return
        }
        rate(isCorrect, feedbackDraft)
        setFeedbackOpen(!compact)
    }

    // Table cells never listen, or every row would rate at once.
    const askingForRating = !compact && !label && !editDisabledReason
    useKeyboardHotkeys(
        {
            y: { action: () => onThumb(true), disabled: !askingForRating || saving },
            n: { action: () => onThumb(false), disabled: !askingForRating || saving },
        },
        [askingForRating, saving, feedbackDraft]
    )

    const buttons = (
        <div className="flex items-center gap-1">
            <LemonButton
                size="xsmall"
                type={thumbsUp ? 'primary' : 'secondary'}
                icon={thumbsUp ? <IconThumbsUpFilled /> : <IconThumbsUp />}
                loading={saving}
                disabledReason={editDisabledReason ?? undefined}
                tooltip={
                    thumbsUp ? (
                        'Remove rating'
                    ) : (
                        <>
                            Scanner got this right
                            {!compact && (
                                <>
                                    {' '}
                                    <KeyboardShortcut y />
                                </>
                            )}
                        </>
                    )
                }
                onClick={() => onThumb(true)}
                data-attr="replay-vision-label-thumbs-up"
            />
            <LemonButton
                size="xsmall"
                type={thumbsDown ? 'primary' : 'secondary'}
                icon={thumbsDown ? <IconThumbsDownFilled /> : <IconThumbsDown />}
                loading={saving}
                disabledReason={editDisabledReason ?? undefined}
                tooltip={
                    thumbsDown ? (
                        'Remove rating'
                    ) : (
                        <>
                            Scanner got this wrong
                            {!compact && (
                                <>
                                    {' '}
                                    <KeyboardShortcut n />
                                </>
                            )}
                        </>
                    )
                }
                onClick={() => onThumb(false)}
                data-attr="replay-vision-label-thumbs-down"
            />
        </div>
    )

    if (compact) {
        return <div className="py-2">{buttons}</div>
    }

    if (label && !feedbackOpen) {
        return null
    }

    return (
        <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 rounded bg-surface-secondary px-3 py-2">
            <span className="text-sm">Did the scanner get this right?</span>
            <Popover
                // Waits for the saved label, since the feedback autosave writes onto it.
                visible={feedbackOpen && !!label}
                onClickOutside={() => setFeedbackOpen(false)}
                placement="bottom-end"
                overlay={
                    <div className="w-80 p-1 flex flex-col gap-2">
                        <span className="text-sm font-medium">Add a note</span>
                        <FeedbackEditor
                            observationId={observationId}
                            initialLabel={initialLabel}
                            onChange={onChange}
                            scannerUserAccessLevel={scannerUserAccessLevel}
                            compact
                            promptForRightAnswer={
                                thumbsDown &&
                                featureFlags[FEATURE_FLAGS.REPLAY_VISION_CALIBRATION_FEEDBACK_PROMPT] === 'test'
                            }
                        />
                        <LemonButton
                            size="small"
                            type="secondary"
                            className="self-end"
                            onClick={() => setFeedbackOpen(false)}
                            data-attr="replay-vision-label-feedback-done"
                        >
                            Done
                        </LemonButton>
                    </div>
                }
            >
                {buttons}
            </Popover>
        </div>
    )
}
