import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect, useState } from 'react'

import { IconThumbsDown, IconThumbsDownFilled, IconThumbsUp, IconThumbsUpFilled } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonModal, LemonTextArea } from '@posthog/lemon-ui'

import { lemonBannerLogic } from 'lib/lemon-ui/LemonBanner/lemonBannerLogic'
import { uuid } from 'lib/utils/dom'
import { getSurveyIdBasedResponseKey, getSurveyResponseKey } from 'scenes/surveys/utils'

import { SurveyEventName, SurveyEventProperties } from '~/types'

type Rating = 'useful' | 'needs improvement'

/** The choice labels the survey's first question stores, so a response is readable in the results. */
const SURVEY_RESPONSES: Record<Rating, string> = {
    useful: 'Useful',
    'needs improvement': 'Needs improvement',
}

export interface FeaturePreviewFeedbackBannerProps {
    /** An `api`-type survey with a single-choice question then an open one. */
    surveyId: string
    ratingQuestionId: string
    feedbackQuestionId: string
    /** Distinguishes responses when several surfaces report to one survey. */
    surface: string
    /** Remembers a dismissal per person, so the banner does not come back on every visit. */
    dismissKey: string
    prompt: string
    modalTitle: string
    feedbackPlaceholder: string
    'data-attr'?: string
}

/**
 * The thumbs-up/thumbs-down strip a feature preview carries while we are still deciding whether to
 * keep it. The rating is recorded on click, so a rating survives someone who never opens the modal,
 * and the written note lands on the same submission id rather than a second response.
 */
export function FeaturePreviewFeedbackBanner({
    surveyId,
    ratingQuestionId,
    feedbackQuestionId,
    surface,
    dismissKey,
    prompt,
    modalTitle,
    feedbackPlaceholder,
    'data-attr': dataAttr,
}: FeaturePreviewFeedbackBannerProps): JSX.Element {
    const [rating, setRating] = useState<Rating | null>(null)
    const [submissionId, setSubmissionId] = useState<string | null>(null)
    const [feedbackText, setFeedbackText] = useState('')
    const [feedbackOpen, setFeedbackOpen] = useState(false)
    // LemonBanner renders nothing once the dismissal is persisted, so without this the impression
    // is recorded on every visit for a banner nobody sees, and the response rate reads far too low.
    const { isDismissed } = useValues(lemonBannerLogic({ dismissKey }))

    useEffect(() => {
        if (isDismissed) {
            return
        }
        posthog.capture(SurveyEventName.SHOWN, {
            [SurveyEventProperties.SURVEY_ID]: surveyId,
            feedback_surface: surface,
        })
    }, [surveyId, surface, isDismissed])

    const ratePreview = (nextRating: Rating): void => {
        if (rating) {
            return
        }

        const nextSubmissionId = uuid()
        const response = SURVEY_RESPONSES[nextRating]

        setRating(nextRating)
        setSubmissionId(nextSubmissionId)
        setFeedbackOpen(true)
        posthog.capture(SurveyEventName.SENT, {
            [SurveyEventProperties.SURVEY_ID]: surveyId,
            [SurveyEventProperties.SURVEY_SUBMISSION_ID]: nextSubmissionId,
            [SurveyEventProperties.SURVEY_COMPLETED]: false,
            [getSurveyResponseKey(0)]: response,
            [getSurveyIdBasedResponseKey(ratingQuestionId)]: response,
            feedback_surface: surface,
        })
    }

    const submitFeedback = (): void => {
        const feedback = feedbackText.trim()
        if (!feedback || !submissionId) {
            return
        }

        posthog.capture(SurveyEventName.SENT, {
            [SurveyEventProperties.SURVEY_ID]: surveyId,
            [SurveyEventProperties.SURVEY_SUBMISSION_ID]: submissionId,
            [SurveyEventProperties.SURVEY_COMPLETED]: true,
            [getSurveyResponseKey(1)]: feedback,
            [getSurveyIdBasedResponseKey(feedbackQuestionId)]: feedback,
            feedback_surface: surface,
        })
        setFeedbackOpen(false)
        setFeedbackText('')
    }

    return (
        <>
            <LemonBanner type="info" dismissKey={dismissKey} className="m-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="text-secondary">{rating ? 'Thanks, your rating is saved.' : prompt}</div>
                    <div className="flex items-center gap-1">
                        <LemonButton
                            type={rating === 'useful' ? 'primary' : 'secondary'}
                            size="xsmall"
                            icon={rating === 'useful' ? <IconThumbsUpFilled /> : <IconThumbsUp />}
                            tooltip="This is useful"
                            disabled={!!rating}
                            onClick={() => ratePreview('useful')}
                            data-attr={dataAttr ? `${dataAttr}-thumbs-up` : undefined}
                        />
                        <LemonButton
                            type={rating === 'needs improvement' ? 'primary' : 'secondary'}
                            size="xsmall"
                            icon={rating === 'needs improvement' ? <IconThumbsDownFilled /> : <IconThumbsDown />}
                            tooltip="Needs improvement"
                            disabled={!!rating}
                            onClick={() => ratePreview('needs improvement')}
                            data-attr={dataAttr ? `${dataAttr}-thumbs-down` : undefined}
                        />
                    </div>
                </div>
            </LemonBanner>
            <LemonModal
                title={modalTitle}
                description="Thanks, your rating is saved. What would make this better?"
                isOpen={feedbackOpen}
                onClose={() => setFeedbackOpen(false)}
                data-attr={dataAttr ? `${dataAttr}-feedback` : undefined}
                footer={
                    <div className="flex justify-end gap-2">
                        <LemonButton type="secondary" onClick={() => setFeedbackOpen(false)}>
                            Not now
                        </LemonButton>
                        <LemonButton type="primary" disabled={!feedbackText.trim()} onClick={submitFeedback}>
                            Send feedback
                        </LemonButton>
                    </div>
                }
            >
                <LemonTextArea
                    value={feedbackText}
                    onChange={setFeedbackText}
                    placeholder={feedbackPlaceholder}
                    minRows={4}
                    autoFocus
                    data-attr={dataAttr ? `${dataAttr}-feedback-text` : undefined}
                />
            </LemonModal>
        </>
    )
}
