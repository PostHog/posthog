import { useActions, useValues } from 'kea'
import { SurveyQuestionType } from 'posthog-js'
import { useId, useState } from 'react'

import { LemonBanner, LemonModal } from '@posthog/lemon-ui'

import { APISurveyForm } from './APISurveyForm'
import { ApiSurveyProps, apiSurveyLogic } from './apiSurveyLogic'
import { SurveyFeedbackButtons } from './SurveyFeedbackButtons'

export function APISurveyFeedback(props: ApiSurveyProps): JSX.Element {
    const logic = apiSurveyLogic(props)
    const { survey, loading, error, answers, ratingAccepted, submitting, completed, submissionId } = useValues(logic)
    const { submitRating } = useActions(logic)
    const [isOpen, setIsOpen] = useState(false)
    const titleId = useId()
    if (loading || !survey) {
        return <APISurveyForm {...props} />
    }
    const question = survey.questions[0]
    if (question.type !== SurveyQuestionType.Rating) {
        return <LemonBanner type="info">This feedback survey needs a rating question first.</LemonBanner>
    }
    if (completed && survey.questions.length === 1) {
        return <div role="status">Thanks for your feedback.</div>
    }
    return (
        <div className="space-y-3">
            <SurveyFeedbackButtons
                question={question}
                value={ratingAccepted ? String(answers[question.id!]) : undefined}
                submissionId={submissionId}
                onChange={submitRating}
                onMoreFeedback={() => setIsOpen(true)}
                loading={submitting}
                expanded={isOpen}
            />
            {error && !isOpen && <LemonBanner type="error">{error}</LemonBanner>}
            <LemonModal
                isOpen={isOpen}
                onClose={() => setIsOpen(false)}
                title={<span id={titleId}>Share more feedback</span>}
                contentRef={(element) => element?.setAttribute('aria-labelledby', titleId)}
                width={520}
                hasUnsavedInput
            >
                {isOpen && <APISurveyForm {...props} answeredQuestionIds={[question.id!]} />}
            </LemonModal>
        </div>
    )
}
