import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect, useState } from 'react'

import { IconThumbsDown, IconThumbsDownFilled, IconThumbsUp, IconThumbsUpFilled } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { lemonBannerLogic } from 'lib/lemon-ui/LemonBanner/lemonBannerLogic'
import { Popover } from 'lib/lemon-ui/Popover'
import { uuid } from 'lib/utils/dom'

import { SurveyEventName, SurveyEventProperties } from '~/types'

import { captureSurveyResponse } from 'products/workflows/frontend/surveyResponseCapture'

import { EmailEditorFeedbackNote } from './EmailEditorFeedbackNote'
import {
    DISMISS_KEY,
    EMAIL_EDITOR_FEEDBACK_RATING_QUESTION_ID,
    EMAIL_EDITOR_FEEDBACK_SURVEY_ID,
    EMAIL_EDITOR_FEEDBACK_TEXT_QUESTION_ID,
} from './emailEditorFeedbackSurvey'
import { useEscapeToClose } from './useEscapeToClose'

type Rating = 'Useful' | 'Needs improvement'

/** Thumbs in the editor toolbar. A rating is saved on click, and the optional note opens next to it. */
export function EmailEditorFeedback(): JSX.Element | null {
    const { isDismissed } = useValues(lemonBannerLogic({ dismissKey: DISMISS_KEY }))
    const { dismiss } = useActions(lemonBannerLogic({ dismissKey: DISMISS_KEY }))
    const [rating, setRating] = useState<Rating | null>(null)
    const [submissionId, setSubmissionId] = useState<string | null>(null)
    const [noteOpen, setNoteOpen] = useState(false)

    useEffect(() => {
        if (!isDismissed) {
            posthog.capture(SurveyEventName.SHOWN, {
                [SurveyEventProperties.SURVEY_ID]: EMAIL_EDITOR_FEEDBACK_SURVEY_ID,
                feedback_surface: 'email-editor',
            })
        }
    }, [isDismissed])

    const closeNote = (): void => {
        setNoteOpen(false)
        dismiss()
    }
    useEscapeToClose(noteOpen, closeNote)

    // A rating hides the thumbs for good once its note is sent or skipped.
    if (isDismissed && !rating) {
        return null
    }

    const rate = (next: Rating): void => {
        const id = uuid()
        setRating(next)
        setSubmissionId(id)
        setNoteOpen(true)
        captureSurveyResponse({
            surveyId: EMAIL_EDITOR_FEEDBACK_SURVEY_ID,
            submissionId: id,
            completed: false,
            answers: [{ questionIndex: 0, questionId: EMAIL_EDITOR_FEEDBACK_RATING_QUESTION_ID, value: next }],
            surface: 'email-editor',
        })
    }

    return (
        <Popover
            visible={noteOpen}
            onClickOutside={closeNote}
            placement="bottom-end"
            overlay={
                <EmailEditorFeedbackNote
                    title={rating === 'Useful' ? 'Thanks! Anything we should keep?' : 'What would make it better?'}
                    placeholder="Tell us what works, what doesn't, or what you'd change"
                    onCancel={closeNote}
                    onSend={(note) => {
                        if (submissionId) {
                            captureSurveyResponse({
                                surveyId: EMAIL_EDITOR_FEEDBACK_SURVEY_ID,
                                submissionId,
                                completed: true,
                                answers: [
                                    {
                                        questionIndex: 1,
                                        questionId: EMAIL_EDITOR_FEEDBACK_TEXT_QUESTION_ID,
                                        value: note,
                                    },
                                ],
                                surface: 'email-editor',
                            })
                        }
                        closeNote()
                    }}
                />
            }
        >
            <div className="flex items-center gap-0.5" data-attr="email-editor-feedback">
                <span className="text-xs text-secondary pr-1">{rating ? 'Thanks!' : 'New editor:'}</span>
                <LemonButton
                    size="xsmall"
                    icon={rating === 'Useful' ? <IconThumbsUpFilled /> : <IconThumbsUp />}
                    tooltip="Working well"
                    aria-label="Working well"
                    disabledReason={rating ? 'Rated' : undefined}
                    onClick={() => rate('Useful')}
                    data-attr="email-editor-feedback-thumbs-up"
                />
                <LemonButton
                    size="xsmall"
                    icon={rating === 'Needs improvement' ? <IconThumbsDownFilled /> : <IconThumbsDown />}
                    tooltip="Needs improvement"
                    aria-label="Needs improvement"
                    disabledReason={rating ? 'Rated' : undefined}
                    onClick={() => rate('Needs improvement')}
                    data-attr="email-editor-feedback-thumbs-down"
                />
            </div>
        </Popover>
    )
}
