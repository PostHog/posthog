import { useActions, useValues } from 'kea'
import { SurveyQuestionType } from 'posthog-js'

import { LemonBanner, LemonButton, Spinner } from '@posthog/lemon-ui'

import { KeyboardShortcut } from 'lib/components/KeyboardShortcut/KeyboardShortcut'

import { ApiSurveyProps, apiSurveyLogic } from './apiSurveyLogic'
import { APISurveyQuestion } from './APISurveyQuestion'
import { advanceSurveyFocus } from './surveyKeyboardNavigation'

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
        <div className="space-y-4" data-attr="api-survey-form" onKeyDown={advanceSurveyFocus}>
            {survey.questions.map((question) => (
                <div key={question.id} className="space-y-2">
                    <APISurveyQuestion
                        question={question}
                        value={answers[question.id!]}
                        onChange={(answer) => setAnswer(question.id!, answer)}
                        onToggleChoice={(choice, checked) => toggleChoice(question.id!, choice, checked)}
                        disabled={submitting}
                    />
                    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-secondary">
                        {question.type === SurveyQuestionType.Open ? (
                            <>
                                <span>
                                    <KeyboardShortcut enter /> new line
                                </span>
                                <span>
                                    <KeyboardShortcut command enter /> continue
                                </span>
                            </>
                        ) : (
                            <>
                                <span>
                                    {question.type === SurveyQuestionType.Rating ? (
                                        <KeyboardShortcut arrowleft arrowright preserveOrder />
                                    ) : (
                                        <KeyboardShortcut arrowup arrowdown preserveOrder />
                                    )}{' '}
                                    <span>
                                        {question.type === SurveyQuestionType.MultipleChoice ? 'move' : 'select'}
                                    </span>
                                </span>
                                {question.type === SurveyQuestionType.MultipleChoice && (
                                    <span>
                                        <KeyboardShortcut space /> toggle
                                    </span>
                                )}
                                <span>
                                    <KeyboardShortcut enter /> continue
                                </span>
                            </>
                        )}
                    </div>
                </div>
            ))}
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-secondary">
                <span>
                    <KeyboardShortcut tab /> next field
                </span>
                <span>
                    <KeyboardShortcut shift tab /> previous field
                </span>
            </div>
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
