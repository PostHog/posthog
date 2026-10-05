import { SurveyQuestion, SurveyQuestionType } from 'posthog-js'
import { useId } from 'react'

import { IconThumbsDown, IconThumbsUp } from '@posthog/icons'
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
    const compactChoices =
        question.type === SurveyQuestionType.Rating ||
        ((question.type === SurveyQuestionType.SingleChoice || question.type === SurveyQuestionType.MultipleChoice) &&
            question.choices.length <= 4 &&
            question.choices.every((choice) => choice.length <= 40))
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
                <div className={question.type === SurveyQuestionType.Rating ? 'w-fit max-w-full space-y-2' : undefined}>
                    <LemonRadio
                        aria-label={question.question}
                        orientation={compactChoices ? 'horizontal' : 'vertical'}
                        className={
                            compactChoices
                                ? 'flex-wrap gap-2 [&_input]:sr-only [&_label]:flex [&_label]:min-w-8 [&_label]:justify-center [&_label]:rounded [&_label]:border [&_label]:border-primary [&_label]:px-3 [&_label]:py-1.5 [&_label:has(input:checked)]:border-accent [&_label:has(input:checked)]:bg-accent-highlight-secondary [&_label:has(input:focus-visible)]:outline [&_label:has(input:focus-visible)]:outline-2 [&_label:has(input:focus-visible)]:outline-offset-2 [&_label:has(input:focus-visible)]:outline-accent'
                                : undefined
                        }
                        value={typeof value === 'string' ? value : undefined}
                        onChange={onChange}
                        options={(question.type === SurveyQuestionType.Rating
                            ? ratingValues(question.scale)
                            : question.choices
                        ).map((choice) => ({
                            value: choice,
                            label:
                                question.type === SurveyQuestionType.Rating && question.display === 'emoji' ? (
                                    <span className="flex items-center gap-2">
                                        {choice === '1' ? <IconThumbsUp /> : <IconThumbsDown />}
                                        <span>
                                            {choice === '1' ? question.lowerBoundLabel : question.upperBoundLabel}
                                        </span>
                                    </span>
                                ) : (
                                    choice
                                ),
                            'aria-label':
                                question.type === SurveyQuestionType.Rating && question.display === 'emoji'
                                    ? choice === '1'
                                        ? question.lowerBoundLabel || 'Thumbs up'
                                        : question.upperBoundLabel || 'Thumbs down'
                                    : undefined,
                            disabledReason: disabled ? 'Response is being sent' : undefined,
                        }))}
                    />
                    {question.type === SurveyQuestionType.Rating && question.display === 'number' && (
                        <div className="flex justify-between gap-4 text-xs text-secondary">
                            <span>{question.lowerBoundLabel}</span>
                            <span>{question.upperBoundLabel}</span>
                        </div>
                    )}
                </div>
            )}
            {question.type === SurveyQuestionType.MultipleChoice && (
                <div
                    role="group"
                    aria-label={question.question}
                    className={compactChoices ? 'flex flex-wrap gap-2' : 'space-y-2'}
                >
                    {question.choices.map((choice) => (
                        <LemonCheckbox
                            key={choice}
                            label={choice}
                            bordered={compactChoices}
                            size={compactChoices ? 'small' : undefined}
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
