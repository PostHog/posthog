import { BuiltLogic, useActions, useValues } from 'kea'
import { SurveyQuestionType } from 'posthog-js'
import { useId } from 'react'

import { LemonButton, LemonCheckbox, LemonLabel, LemonTextArea } from '@posthog/lemon-ui'

import { LemonRadio } from 'lib/lemon-ui/LemonRadio'

import { feedbackRecordingLogic } from './feedbackRecordingLogic'
import { mcpAnalyticsFeedbackLogicType } from './mcpAnalyticsFeedbackLogic'
import { MCPFeedbackVoiceInput } from './MCPFeedbackVoiceInput'
import { ratingValues } from './surveyQuestions'

export function MCPFeedbackFollowUp({
    feedback,
}: {
    feedback: BuiltLogic<mcpAnalyticsFeedbackLogicType>
}): JSX.Element {
    const fieldId = useId()
    const {
        survey,
        prompt,
        answer,
        responses,
        voiceAvailable,
        submissionId,
        submitting,
        canComplete,
        voiceQuestionIds,
    } = useValues(feedback)
    const { setResponse, submitResponse } = useActions(feedback)
    const voiceQuestion = survey?.questions.find((question) => question.type === SurveyQuestionType.Open)
    const recording = feedbackRecordingLogic({
        id: submissionId,
        onTranscript: (text) => {
            if (voiceQuestion?.id) {
                const existing = responses[voiceQuestion.id]
                setResponse(
                    voiceQuestion.id,
                    typeof existing === 'string' && existing.trim() ? `${existing}\n${text}` : text,
                    true
                )
            }
        },
    })
    const { status } = useValues(recording)
    const busy = submitting || status !== 'idle'
    return (
        <div className="space-y-3 max-h-96 overflow-y-auto">
            <div className="text-secondary text-xs" role="status">
                Thanks for answering.
            </div>
            {survey?.questions.slice(1).map((question, index) => {
                const id = question.id!
                const value = responses[id]
                const label = (index === 0 ? prompt.followUpQuestion : undefined) ?? question.question
                return (
                    <div key={id} className="space-y-2">
                        <LemonLabel htmlFor={`${fieldId}-${id}`} showOptional={question.optional}>
                            {label}
                        </LemonLabel>
                        {question.description && <div className="text-secondary text-xs">{question.description}</div>}
                        {question.type === SurveyQuestionType.Open && (
                            <>
                                <LemonTextArea
                                    id={`${fieldId}-${id}`}
                                    value={typeof value === 'string' ? value : ''}
                                    onChange={(text) => setResponse(id, text)}
                                    minRows={2}
                                    maxRows={4}
                                    maxLength={2000}
                                    disabled={busy}
                                    data-attr="mcp-analytics-feedback-detail"
                                />
                                {voiceQuestionIds.includes(id) && (
                                    <div className="text-xs text-secondary" role="status">
                                        Review and edit the transcript before sending your feedback.
                                    </div>
                                )}
                                {voiceAvailable && voiceQuestion?.id === id && (
                                    <MCPFeedbackVoiceInput logic={recording} disabled={submitting} />
                                )}
                            </>
                        )}
                        {(question.type === SurveyQuestionType.SingleChoice ||
                            question.type === SurveyQuestionType.Rating) && (
                            <LemonRadio
                                aria-label={label}
                                value={typeof value === 'string' ? value : undefined}
                                onChange={(choice) => setResponse(id, choice)}
                                options={(question.type === SurveyQuestionType.Rating
                                    ? ratingValues(question.scale)
                                    : question.choices
                                ).map((choice) => ({
                                    value: choice,
                                    label: choice,
                                    disabledReason: busy ? 'Finish your recording or submission first' : undefined,
                                    'data-attr': 'mcp-feedback-choice',
                                }))}
                            />
                        )}
                        {question.type === SurveyQuestionType.MultipleChoice && (
                            <div className="space-y-2" role="group" aria-label={label}>
                                {question.choices.map((choice) => (
                                    <LemonCheckbox
                                        key={choice}
                                        label={choice}
                                        checked={Array.isArray(value) && value.includes(choice)}
                                        disabled={busy}
                                        onChange={(checked) =>
                                            setResponse(
                                                id,
                                                checked
                                                    ? [...(Array.isArray(value) ? value : []), choice]
                                                    : (Array.isArray(value) ? value : []).filter(
                                                          (item) => item !== choice
                                                      )
                                            )
                                        }
                                        data-attr="mcp-feedback-choice"
                                    />
                                ))}
                            </div>
                        )}
                    </div>
                )
            })}
            <LemonButton
                type="primary"
                size="small"
                loading={submitting}
                disabledReason={
                    status !== 'idle'
                        ? 'Finish or discard your recording first'
                        : !canComplete
                          ? 'Answer the required questions first'
                          : undefined
                }
                onClick={() => submitResponse(answer, true)}
                data-attr="mcp-analytics-feedback-submit"
            >
                Send feedback
            </LemonButton>
        </div>
    )
}
