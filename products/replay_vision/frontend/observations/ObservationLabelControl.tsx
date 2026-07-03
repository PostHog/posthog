import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconThumbsDown, IconThumbsDownFilled, IconThumbsUp, IconThumbsUpFilled } from '@posthog/icons'
import { LemonButton, LemonTextArea, Tooltip } from '@posthog/lemon-ui'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { ReplayObservationLabelApi } from '../generated/api.schemas'
import { observationLabelLogic } from './observationLabelLogic'

export interface ObservationLabelProps {
    observationId: string
    initialLabel?: ReplayObservationLabelApi | null
    onChange?: (label: ReplayObservationLabelApi | null) => void
}

const FEEDBACK_PLACEHOLDER = 'Optional: what did it get right or wrong, and why? Used to improve the prompt.'

function useEditAccess(): string | null {
    // Editing the shared rating mutates team-wide data, so it needs edit access (matches the "Edit scanner" gate).
    return getAccessControlDisabledReason(AccessControlResourceType.SessionRecording, AccessControlLevel.Editor)
}

function FeedbackEditor({
    observationId,
    initialLabel,
    onChange,
    compact,
    onBlur,
}: ObservationLabelProps & { compact: boolean; onBlur?: () => void }): JSX.Element {
    const logic = observationLabelLogic({ observationId, initialLabel, onChange })
    const { label, saving, feedbackDraft } = useValues(logic)
    const { setFeedbackDraft } = useActions(logic)
    const canEdit = !useEditAccess()
    const feedbackSynced = feedbackDraft === (label?.feedback ?? '')

    return (
        <div className="space-y-1">
            <LemonTextArea
                placeholder={FEEDBACK_PLACEHOLDER}
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
                    <span className="text-xs text-muted" data-attr="replay-vision-label-feedback-status">
                        {saving || !feedbackSynced ? 'Saving…' : 'Saved'}
                    </span>
                </div>
            )}
        </div>
    )
}

/**
 * Feedback cell for the quality table: optional written context on a rated observation (thumbs up or down).
 * Collapses to a truncated one-liner until clicked, so only the row being edited grows. Unrated rows
 * show a hint to rate first, since feedback lives on the shared label.
 */
export function ObservationLabelFeedback({
    observationId,
    initialLabel,
    onChange,
}: ObservationLabelProps): JSX.Element {
    const logic = observationLabelLogic({ observationId, initialLabel, onChange })
    const { label, feedbackDraft } = useValues(logic)
    const [editing, setEditing] = useState(false)
    const canEdit = !useEditAccess()

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
            compact
            onBlur={() => setEditing(false)}
        />
    )
}

/**
 * Thumbs up/down rating on whether the scanner got this session right. The rating is shared across the
 * team (one per observation) and gathered later to improve the scanner prompt. `compact` renders just the
 * buttons for table cells (feedback lives in its own column via `ObservationLabelFeedback`); the default
 * adds the bordered card, question, and inline feedback editor for the detail page.
 */
export function ObservationLabelControl({
    observationId,
    initialLabel,
    onChange,
    compact = false,
}: ObservationLabelProps & { compact?: boolean }): JSX.Element {
    const logic = observationLabelLogic({ observationId, initialLabel, onChange })
    const { label, saving, feedbackDraft } = useValues(logic)
    const { rate, clearRating } = useActions(logic)

    const thumbsUp = label?.is_correct === true
    const thumbsDown = label?.is_correct === false
    const editDisabledReason = useEditAccess()
    const canEdit = !editDisabledReason

    const buttons = (
        <div className="flex items-center gap-1">
            <LemonButton
                size="xsmall"
                type={thumbsUp ? 'primary' : 'secondary'}
                icon={thumbsUp ? <IconThumbsUpFilled /> : <IconThumbsUp />}
                loading={saving}
                disabledReason={editDisabledReason ?? undefined}
                tooltip="Scanner got this right"
                onClick={() => rate(true, feedbackDraft)}
                data-attr="replay-vision-label-thumbs-up"
            />
            <LemonButton
                size="xsmall"
                type={thumbsDown ? 'primary' : 'secondary'}
                icon={thumbsDown ? <IconThumbsDownFilled /> : <IconThumbsDown />}
                loading={saving}
                disabledReason={editDisabledReason ?? undefined}
                tooltip="Scanner got this wrong"
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

    if (compact) {
        return <div className="py-1">{buttons}</div>
    }

    return (
        <div className="border rounded p-3 bg-surface-primary space-y-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-sm font-medium">Did the scanner get this right?</span>
                {buttons}
            </div>
            {label && (
                <FeedbackEditor
                    observationId={observationId}
                    initialLabel={initialLabel}
                    onChange={onChange}
                    compact={false}
                />
            )}
        </div>
    )
}
