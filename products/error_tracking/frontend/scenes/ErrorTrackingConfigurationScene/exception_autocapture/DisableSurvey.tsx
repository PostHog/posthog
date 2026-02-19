import { useActions, useValues } from 'kea'

import { LemonButton, LemonTextArea } from '@posthog/lemon-ui'

import { LemonRadio } from 'lib/lemon-ui/LemonRadio'

import { SurveyQuestionType } from '~/types'

import { disableSurveyLogic } from './disableSurveyLogic'

export function DisableSurvey(): JSX.Element | null {
    const { visible, surveyQuestions, selectedChoice, openResponse, submitted } = useValues(disableSurveyLogic)
    const { setSelectedChoice, setOpenResponse, submitResponse } = useActions(disableSurveyLogic)

    if (!visible) {
        return null
    }

    return (
        <div className="mt-4 max-w-lg border rounded-lg p-4 bg-bg-light">
            {submitted ? (
                <p className="font-medium m-0">Thanks for your feedback!</p>
            ) : (
                <div className="flex flex-col gap-3">
                    {surveyQuestions.map((question, index) => (
                        <div key={index}>
                            <label className="font-medium m-0">{question.question}</label>
                            {question.type === SurveyQuestionType.SingleChoice && (
                                <LemonRadio
                                    className="mt-2"
                                    value={selectedChoice}
                                    onChange={setSelectedChoice}
                                    options={question.choices.map((choice) => ({
                                        label: choice,
                                        value: choice,
                                    }))}
                                />
                            )}
                            {question.type === SurveyQuestionType.Open && (
                                <LemonTextArea
                                    className="mt-2"
                                    placeholder="Share your feedback..."
                                    value={openResponse}
                                    onChange={setOpenResponse}
                                    rows={3}
                                />
                            )}
                        </div>
                    ))}
                    <div>
                        <LemonButton
                            type="primary"
                            size="small"
                            disabledReason={
                                !selectedChoice && !openResponse.trim()
                                    ? 'Please select an option or enter feedback'
                                    : undefined
                            }
                            onClick={submitResponse}
                        >
                            Submit
                        </LemonButton>
                    </div>
                </div>
            )}
        </div>
    )
}
