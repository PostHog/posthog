import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, Spinner } from '@posthog/lemon-ui'

import { ApiSurveyProps, apiSurveyLogic } from './apiSurveyLogic'
import { APISurveyQuestion } from './APISurveyQuestion'

export function APISurveyForm(props: ApiSurveyProps): JSX.Element {
    const logic = apiSurveyLogic(props)
    const { survey, loading, error, answers, canSubmit, completed, submitting } = useValues(logic)
    const { loadSurvey, setAnswer, toggleChoice, submit } = useActions(logic)
    if (loading) {
        return <Spinner />
    }
    if (!survey) {
        return (
            <div className="space-y-3">
                <LemonBanner type={error ? 'error' : 'info'}>{error || 'This survey is not available.'}</LemonBanner>
                <LemonButton onClick={loadSurvey}>Try again</LemonButton>
            </div>
        )
    }
    if (completed) {
        return <div role="status">Thanks for your feedback.</div>
    }
    return (
        <div className="space-y-4" data-attr="api-survey-form">
            {survey.questions.map((question) => (
                <APISurveyQuestion
                    key={question.id}
                    question={question}
                    value={answers[question.id!]}
                    onChange={(answer) => setAnswer(question.id!, answer)}
                    onToggleChoice={(choice, checked) => toggleChoice(question.id!, choice, checked)}
                    disabled={submitting}
                />
            ))}
            {error && <LemonBanner type="error">{error}</LemonBanner>}
            <LemonButton
                type="primary"
                loading={submitting}
                disabledReason={!canSubmit ? 'Complete the required answers and check their limits' : undefined}
                onClick={submit}
                data-attr="api-survey-submit"
            >
                Send feedback
            </LemonButton>
        </div>
    )
}
