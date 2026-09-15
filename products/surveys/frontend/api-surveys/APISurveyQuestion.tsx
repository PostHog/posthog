import { SurveyQuestion, SurveyQuestionType } from 'posthog-js'
import { useId } from 'react'

import { LemonCheckbox, LemonLabel, LemonTextArea } from '@posthog/lemon-ui'

import { LemonRadio } from 'lib/lemon-ui/LemonRadio'

import { navigateSurveyChoices } from './surveyKeyboardNavigation'
import { SurveyAnswer, ratingValues } from './surveyQuestions'

export function APISurveyQuestion({
    question,
    value,
    onChange,
    onToggleChoice,
    disabled,
}: {
    question: SurveyQuestion
    value?: SurveyAnswer
    onChange: (answer: SurveyAnswer) => void
    onToggleChoice: (choice: string, checked: boolean) => void
    disabled?: boolean
}): JSX.Element {
    const id = useId()
    return (
        <div className="space-y-2" data-survey-question={question.id} onKeyDown={navigateSurveyChoices}>
            <LemonLabel htmlFor={id} showOptional={question.optional}>
                {question.question}
            </LemonLabel>
            {question.description && <div className="text-secondary text-xs">{question.description}</div>}
            {question.type === SurveyQuestionType.Open && (
                <LemonTextArea
                    id={id}
                    value={typeof value === 'string' ? value : ''}
                    onChange={onChange}
                    minRows={2}
                    maxRows={5}
                    maxLength={2000}
                    disabled={disabled}
                    data-attr="api-survey-text"
                />
            )}
            {(question.type === SurveyQuestionType.SingleChoice || question.type === SurveyQuestionType.Rating) && (
                <>
                    <LemonRadio
                        aria-label={question.question}
                        value={typeof value === 'string' ? value : undefined}
                        onChange={onChange}
                        options={(question.type === SurveyQuestionType.Rating
                            ? ratingValues(question.scale)
                            : question.choices
                        ).map((choice) => ({
                            value: choice,
                            label:
                                question.type === SurveyQuestionType.Rating && question.display === 'emoji'
                                    ? choice === '1'
                                        ? '👍'
                                        : '👎'
                                    : choice,
                            disabledReason: disabled ? 'Response is being sent' : undefined,
                        }))}
                    />
                    {question.type === SurveyQuestionType.Rating && (
                        <div className="flex justify-between gap-4 text-xs text-secondary">
                            <span>{question.lowerBoundLabel}</span>
                            <span>{question.upperBoundLabel}</span>
                        </div>
                    )}
                </>
            )}
            {question.type === SurveyQuestionType.MultipleChoice && (
                <div role="group" aria-label={question.question} className="space-y-2">
                    {question.choices.map((choice) => (
                        <LemonCheckbox
                            key={choice}
                            label={choice}
                            checked={Array.isArray(value) && value.includes(choice)}
                            onChange={(checked) => onToggleChoice(choice, checked)}
                            disabled={disabled}
                            data-attr="api-survey-choice"
                        />
                    ))}
                </div>
            )}
        </div>
    )
}
