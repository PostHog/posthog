import { useActions, useValues } from 'kea'
import { useId } from 'react'

import {
    Button,
    Card,
    CardContent,
    Field,
    FieldLabel,
    FieldLegend,
    FieldSet,
    RadioGroup,
    RadioGroupItem,
    Text,
    Textarea,
} from '@posthog/quill'

import { SurveyQuestionType } from '~/types'

import { disableSurveyLogic } from './disableSurveyLogic'

export function QuillDisableSurvey({ submitDisabledReason }: { submitDisabledReason?: string }): JSX.Element {
    const { surveyQuestions, selectedChoice, openResponse, submitted } = useValues(disableSurveyLogic)
    const { setSelectedChoice, setOpenResponse, submitResponse } = useActions(disableSurveyLogic)
    const idPrefix = useId()

    return (
        <Card size="sm" className="max-w-lg">
            <CardContent className="flex flex-col gap-3">
                {submitted ? (
                    <Text size="xs" weight="medium" render={<p className="m-0" />}>
                        Thanks for your feedback!
                    </Text>
                ) : (
                    <>
                        {surveyQuestions.map((question, index) => {
                            const questionId = `${idPrefix}-${index}`

                            if (question.type === SurveyQuestionType.SingleChoice) {
                                return (
                                    <FieldSet key={index}>
                                        <FieldLegend variant="label">{question.question}</FieldLegend>
                                        <RadioGroup
                                            value={selectedChoice ?? ''}
                                            onValueChange={(value) => setSelectedChoice(value as string)}
                                        >
                                            {question.choices.map((choice) => {
                                                const choiceId = `${questionId}-${choice}`

                                                return (
                                                    <Field key={choice} orientation="horizontal">
                                                        <RadioGroupItem id={choiceId} value={choice} />
                                                        <FieldLabel htmlFor={choiceId}>{choice}</FieldLabel>
                                                    </Field>
                                                )
                                            })}
                                        </RadioGroup>
                                    </FieldSet>
                                )
                            }

                            if (question.type === SurveyQuestionType.Open) {
                                return (
                                    <Field key={index}>
                                        <FieldLabel htmlFor={questionId}>{question.question}</FieldLabel>
                                        <Textarea
                                            id={questionId}
                                            placeholder="Share your feedback..."
                                            value={openResponse}
                                            onChange={(event) => setOpenResponse(event.target.value)}
                                            rows={3}
                                        />
                                    </Field>
                                )
                            }

                            return (
                                <Text key={index} size="xs" weight="medium" render={<p className="m-0" />}>
                                    {question.question}
                                </Text>
                            )
                        })}
                        <div>
                            <Button variant="primary" disabledReason={submitDisabledReason} onClick={submitResponse}>
                                Submit
                            </Button>
                        </div>
                    </>
                )}
            </CardContent>
        </Card>
    )
}
