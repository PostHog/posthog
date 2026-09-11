import {
    LogicWrapper,
    MakeLogicType,
    actions,
    afterMount,
    getContext,
    kea,
    key,
    listeners,
    path,
    props,
    reducers,
} from 'kea'
import posthog, { Survey, SurveyQuestionType, SurveyType } from 'posthog-js'

import { MCP_ANALYTICS_FEEDBACK_PROPERTIES, MCP_ANALYTICS_USEFULNESS_SURVEY_ID } from './constants'

export const FEEDBACK_PROMPT_DELAY_MS = 30_000
export const FEEDBACK_PROMPT_COOLDOWN_MS = 30 * 24 * 60 * 60 * 1000

export interface MCPAnalyticsFeedbackLogicProps {
    userId: string
    sessionId: string
    isImpersonated: boolean
}

export interface mcpAnalyticsFeedbackLogicValues {
    visible: boolean
    lastPromptAt: number
    survey: Survey | null
    submissionId: string
    answer: string
    detail: string
    completed: boolean
    submitting: boolean
    error: boolean
}

export interface mcpAnalyticsFeedbackLogicActions {
    schedulePrompt: (survey: Survey | null) => { survey: Survey | null }
    showPrompt: (
        survey: Survey,
        timestamp: number,
        submissionId: string
    ) => { survey: Survey; timestamp: number; submissionId: string }
    dismissPrompt: () => { value: true }
    setDetail: (detail: string) => { detail: string }
    submitResponse: (answer: string, completed: boolean) => { answer: string; completed: boolean }
    responseQueued: (answer: string, completed: boolean) => { answer: string; completed: boolean }
    responseFailed: () => { value: true }
}

export type mcpAnalyticsFeedbackLogicType = MakeLogicType<
    mcpAnalyticsFeedbackLogicValues,
    mcpAnalyticsFeedbackLogicActions,
    MCPAnalyticsFeedbackLogicProps
>

function hasFeedbackQuestions(survey: Survey): boolean {
    const [choice, detail] = survey.questions
    return (
        survey.questions.length === 2 &&
        choice.type === SurveyQuestionType.SingleChoice &&
        !!choice.id &&
        choice.choices.length > 0 &&
        detail.type === SurveyQuestionType.Open &&
        !!detail.id &&
        !!detail.optional
    )
}

export const mcpAnalyticsFeedbackLogic: LogicWrapper<mcpAnalyticsFeedbackLogicType> =
    kea<mcpAnalyticsFeedbackLogicType>([
        props({} as MCPAnalyticsFeedbackLogicProps),
        key(({ userId, sessionId }) => `${userId}:${sessionId}`),
        path((key) => ['products', 'mcp_analytics', 'frontend', 'feedback', 'mcpAnalyticsFeedbackLogic', key]),
        actions({
            schedulePrompt: (survey: Survey | null) => ({ survey }),
            showPrompt: (survey: Survey, timestamp: number, submissionId: string) => ({
                survey,
                timestamp,
                submissionId,
            }),
            dismissPrompt: true,
            setDetail: (detail: string) => ({ detail }),
            submitResponse: (answer: string, completed: boolean) => ({ answer, completed }),
            responseQueued: (answer: string, completed: boolean) => ({ answer, completed }),
            responseFailed: true,
        }),
        reducers(({ props }) => ({
            visible: [false, { showPrompt: () => true, dismissPrompt: () => false }],
            survey: [null as Survey | null, { showPrompt: (_, { survey }) => survey }],
            submissionId: ['', { showPrompt: (_, { submissionId }) => submissionId }],
            answer: ['', { responseQueued: (_, { answer }) => answer }],
            detail: ['', { setDetail: (_, { detail }) => detail }],
            completed: [false, { responseQueued: (_, { completed }) => completed }],
            submitting: [
                false,
                { submitResponse: () => true, responseQueued: () => false, responseFailed: () => false },
            ],
            error: [false, { submitResponse: () => false, responseFailed: () => true }],
            lastPromptAt: [
                0,
                { persist: true, storageKey: `mcp-analytics-feedback-last-prompt:${props.userId}` },
                { showPrompt: (_, { timestamp }) => timestamp },
            ],
        })),
        listeners(({ actions, values, props, cache }) => ({
            schedulePrompt: ({ survey }) => {
                cache.disposables.dispose('prompt-delay')
                if (
                    !props.userId ||
                    props.isImpersonated ||
                    values.visible ||
                    !survey ||
                    survey.type !== SurveyType.API ||
                    !survey.start_date ||
                    survey.end_date ||
                    !hasFeedbackQuestions(survey) ||
                    !posthog.is_capturing() ||
                    Date.now() - values.lastPromptAt < FEEDBACK_PROMPT_COOLDOWN_MS
                ) {
                    return
                }
                const context = getContext()
                cache.disposables.add(() => {
                    const timer = window.setTimeout(() => {
                        if (getContext() !== context) {
                            return
                        }
                        if (posthog.is_capturing()) {
                            actions.showPrompt(survey, Date.now(), crypto.randomUUID())
                        }
                        cache.disposables.dispose('prompt-delay')
                    }, FEEDBACK_PROMPT_DELAY_MS)
                    return () => window.clearTimeout(timer)
                }, 'prompt-delay')
            },
            showPrompt: ({ survey, submissionId }) => {
                posthog.capture('survey shown', {
                    ...MCP_ANALYTICS_FEEDBACK_PROPERTIES,
                    $survey_id: survey.id,
                    $survey_name: survey.name,
                    $survey_submission_id: submissionId,
                })
            },
            dismissPrompt: () => {
                if (values.survey && !values.completed) {
                    posthog.capture('survey dismissed', {
                        ...MCP_ANALYTICS_FEEDBACK_PROPERTIES,
                        $survey_id: values.survey.id,
                        $survey_name: values.survey.name,
                        $survey_submission_id: values.submissionId,
                        $survey_partially_completed: !!values.answer,
                    })
                }
            },
            submitResponse: ({ answer, completed }) => {
                const { survey } = values
                if (
                    !values.visible ||
                    !survey ||
                    values.completed ||
                    (completed ? !values.answer || answer !== values.answer : !!values.answer) ||
                    survey.questions[0].type !== SurveyQuestionType.SingleChoice ||
                    !survey.questions[0].choices.includes(answer)
                ) {
                    actions.responseQueued(values.answer, values.completed)
                    return
                }
                try {
                    const queued = posthog.capture('survey sent', {
                        ...MCP_ANALYTICS_FEEDBACK_PROPERTIES,
                        $survey_id: survey.id,
                        $survey_name: survey.name,
                        $survey_submission_id: values.submissionId,
                        $survey_completed: completed,
                        $survey_questions: survey.questions.map(({ id, question }) => ({ id, question })),
                        [`$survey_response_${survey.questions[0].id}`]: answer,
                        ...(completed && values.detail.trim()
                            ? { [`$survey_response_${survey.questions[1].id}`]: values.detail.trim() }
                            : {}),
                    })
                    if (queued) {
                        actions.responseQueued(answer, completed)
                    } else {
                        actions.responseFailed()
                    }
                } catch {
                    actions.responseFailed()
                }
            },
        })),
        afterMount(({ actions, cache }) => {
            const context = getContext()
            cache.disposables.add(() =>
                posthog.onSurveysLoaded((_, surveyContext) => {
                    if (surveyContext?.isLoaded) {
                        cache.disposables.add(
                            () =>
                                posthog.onFeatureFlags(() => {
                                    posthog.getActiveMatchingSurveys((surveys) => {
                                        if (!cache.disposables.isDisposed && getContext() === context) {
                                            actions.schedulePrompt(
                                                surveys.find(({ id }) => id === MCP_ANALYTICS_USEFULNESS_SURVEY_ID) ??
                                                    null
                                            )
                                        }
                                    })
                                }),
                            'survey-flags'
                        )
                    }
                })
            )
        }),
    ])
