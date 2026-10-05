import { useActions, useValues } from 'kea'
import { SurveyQuestionType } from 'posthog-js'
import { useEffect, useId, useRef, useState } from 'react'

import { LemonBanner, LemonModal } from '@posthog/lemon-ui'

import { APISurveyForm } from './APISurveyForm'
import { ApiSurveyProps, apiSurveyLogic } from './apiSurveyLogic'
import { SurveyFeedbackButtons } from './SurveyFeedbackButtons'

export function APISurveyFeedback(props: ApiSurveyProps): JSX.Element {
    const logic = apiSurveyLogic(props)
    const { survey, loading, error, answers, ratingAccepted, submitting, completed, submissionId } = useValues(logic)
    const { submitRating, editRating } = useActions(logic)
    const [isOpen, setIsOpen] = useState(false)
    const titleId = useId()
    const completedRef = useRef<HTMLDivElement>(null)
    useEffect(() => {
        if (completed && !isOpen) {
            completedRef.current?.focus()
        }
    }, [completed, isOpen])
    if (loading || !survey) {
        return <APISurveyForm {...props} />
    }
    const question = survey.questions[0]
    if (question.type !== SurveyQuestionType.Rating) {
        return <LemonBanner type="info">This feedback survey needs a rating question first.</LemonBanner>
    }
    if (completed && !isOpen) {
        return (
            <div ref={completedRef} role="status" tabIndex={-1}>
                Thanks for your feedback.
            </div>
        )
    }
    return (
        <div className="space-y-3">
            {completed ? (
                <span>Thanks for your feedback.</span>
            ) : (
                <SurveyFeedbackButtons
                    question={question}
                    value={answers[question.id!] as string | undefined}
                    accepted={ratingAccepted}
                    requiresCompletion={!survey.enable_partial_responses}
                    onEdit={editRating}
                    submissionId={submissionId}
                    onChange={submitRating}
                    onMoreFeedback={() => setIsOpen(true)}
                    loading={submitting}
                    expanded={isOpen}
                />
            )}
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
