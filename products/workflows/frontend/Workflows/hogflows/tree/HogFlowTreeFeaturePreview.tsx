import posthog from 'posthog-js'
import { useEffect, useState } from 'react'

import { IconThumbsDown, IconThumbsDownFilled, IconThumbsUp, IconThumbsUpFilled } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonModal, LemonTextArea } from '@posthog/lemon-ui'

import { uuid } from 'lib/utils/dom'
import { getSurveyIdBasedResponseKey, getSurveyResponseKey } from 'scenes/surveys/utils'

import { SurveyEventName, SurveyEventProperties } from '~/types'

const SURVEY_ID = '01a0856f-7ae3-0000-eef6-fec0a2e1b78f'
const RATING_QUESTION_ID = 'a899da8d-092a-41ce-ab9b-8e18b2c7cfd8'
const FEEDBACK_QUESTION_ID = 'acbad4b5-52c2-4a56-a280-5d2ddd064612'

type WorkflowTreeFeedbackRating = 'useful' | 'needs improvement'

const surveyResponses: Record<WorkflowTreeFeedbackRating, string> = {
    useful: 'Useful',
    'needs improvement': 'Needs improvement',
}

export function HogFlowTreeFeaturePreview(): JSX.Element {
    const [rating, setRating] = useState<WorkflowTreeFeedbackRating | null>(null)
    const [submissionId, setSubmissionId] = useState<string | null>(null)
    const [feedbackText, setFeedbackText] = useState('')
    const [feedbackOpen, setFeedbackOpen] = useState(false)

    useEffect(() => {
        posthog.capture(SurveyEventName.SHOWN, {
            [SurveyEventProperties.SURVEY_ID]: SURVEY_ID,
            feedback_surface: 'workflow_tree_editor',
        })
    }, [])

    const ratePreview = (nextRating: WorkflowTreeFeedbackRating): void => {
        if (rating) {
            return
        }

        const nextSubmissionId = uuid()
        const response = surveyResponses[nextRating]

        setRating(nextRating)
        setSubmissionId(nextSubmissionId)
        setFeedbackOpen(true)
        posthog.capture(SurveyEventName.SENT, {
            [SurveyEventProperties.SURVEY_ID]: SURVEY_ID,
            [SurveyEventProperties.SURVEY_SUBMISSION_ID]: nextSubmissionId,
            [SurveyEventProperties.SURVEY_COMPLETED]: false,
            [getSurveyResponseKey(0)]: response,
            [getSurveyIdBasedResponseKey(RATING_QUESTION_ID)]: response,
            feedback_surface: 'workflow_tree_editor',
        })
    }

    const submitFeedback = (): void => {
        const feedback = feedbackText.trim()
        if (!feedback || !submissionId) {
            return
        }

        posthog.capture(SurveyEventName.SENT, {
            [SurveyEventProperties.SURVEY_ID]: SURVEY_ID,
            [SurveyEventProperties.SURVEY_SUBMISSION_ID]: submissionId,
            [SurveyEventProperties.SURVEY_COMPLETED]: true,
            [getSurveyResponseKey(1)]: feedback,
            [getSurveyIdBasedResponseKey(FEEDBACK_QUESTION_ID)]: feedback,
            feedback_surface: 'workflow_tree_editor',
        })
        setFeedbackOpen(false)
        setFeedbackText('')
    }

    return (
        <>
            <LemonBanner type="info" dismissKey="workflow-tree-feature-preview" className="m-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="text-secondary">
                        {rating
                            ? 'Thanks, your rating is saved.'
                            : 'We’re trialling a new list based workflow view. What do you think?'}
                    </div>
                    <div className="flex items-center gap-1">
                        <LemonButton
                            type={rating === 'useful' ? 'primary' : 'secondary'}
                            size="xsmall"
                            icon={rating === 'useful' ? <IconThumbsUpFilled /> : <IconThumbsUp />}
                            tooltip="This is useful"
                            disabled={!!rating}
                            onClick={() => ratePreview('useful')}
                            data-attr="workflow-tree-feature-preview-thumbs-up"
                        />
                        <LemonButton
                            type={rating === 'needs improvement' ? 'primary' : 'secondary'}
                            size="xsmall"
                            icon={rating === 'needs improvement' ? <IconThumbsDownFilled /> : <IconThumbsDown />}
                            tooltip="Needs improvement"
                            disabled={!!rating}
                            onClick={() => ratePreview('needs improvement')}
                            data-attr="workflow-tree-feature-preview-thumbs-down"
                        />
                    </div>
                </div>
            </LemonBanner>
            <LemonModal
                title="Help shape the new workflow view"
                description="Thanks, your rating is saved. What would make this better?"
                isOpen={feedbackOpen}
                onClose={() => setFeedbackOpen(false)}
                data-attr="workflow-tree-feature-preview-feedback"
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
                    placeholder="Tell us what works, what doesn’t, or what you’d change"
                    minRows={4}
                    autoFocus
                    data-attr="workflow-tree-feature-preview-feedback-text"
                />
            </LemonModal>
        </>
    )
}
