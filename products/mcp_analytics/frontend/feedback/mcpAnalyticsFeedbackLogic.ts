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
    selectors,
} from 'kea'
import posthog, { Survey, SurveyQuestionType, SurveyType } from 'posthog-js'

import { MCPAnalyticsFeedbackPromptConfig, MCP_ANALYTICS_USEFULNESS_SURVEY_ID } from './constants'

export const FEEDBACK_PROMPT_DELAY_MS = 30_000
export const FEEDBACK_PROMPT_COOLDOWN_MS = 30 * 24 * 60 * 60 * 1000

export interface MCPAnalyticsFeedbackLogicProps {
    userId: string
    contextKey: string
    prompt: MCPAnalyticsFeedbackPromptConfig
    isImpersonated: boolean
}

export interface mcpAnalyticsFeedbackLogicValues {
    prompt: MCPAnalyticsFeedbackPromptConfig
    surveyEventProperties: Record<string, unknown>
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
        choice.type === SurveyQuestionType.Rating &&
        !!choice.id &&
        choice.scale === 2 &&
        choice.display === 'emoji' &&
        detail.type === SurveyQuestionType.Open &&
        !!detail.id &&
        !!detail.optional
    )
}

export const mcpAnalyticsFeedbackLogic: LogicWrapper<mcpAnalyticsFeedbackLogicType> =
    kea<mcpAnalyticsFeedbackLogicType>([
        props({} as MCPAnalyticsFeedbackLogicProps),
        key(({ userId, contextKey, prompt }) => JSON.stringify([userId, prompt.entryPoint, contextKey])),
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
            prompt: [props.prompt, { showPrompt: () => ({ ...props.prompt }) }],
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
        selectors({
            surveyEventProperties: [
                (s) => [s.survey, s.submissionId, s.prompt],
                (
                    survey: Survey | null,
                    submissionId: string,
                    prompt: MCPAnalyticsFeedbackPromptConfig
                ): Record<string, unknown> => ({
                    feedback_surface: 'mcp_analytics',
                    feedback_entry_point: prompt.entryPoint,
                    mcp_analytics_tab: prompt.tab,
                    feedback_question_version: prompt.version,
                    feedback_question: prompt.question,
                    feedback_followup_question: prompt.followUpQuestion,
                    $survey_id: survey?.id,
                    $survey_name: survey?.name,
                    $survey_submission_id: submissionId,
                    $survey_questions: survey?.questions.map(({ id }, index) => ({
                        id,
                        question: index === 0 ? prompt.question : prompt.followUpQuestion,
                    })),
                }),
            ],
        }),
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
            showPrompt: () => {
                posthog.capture('survey shown', values.surveyEventProperties)
            },
            dismissPrompt: () => {
                if (values.survey && !values.completed) {
                    posthog.capture('survey dismissed', {
                        ...values.surveyEventProperties,
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
                    !hasFeedbackQuestions(survey) ||
                    !['1', '2'].includes(answer)
                ) {
                    actions.responseQueued(values.answer, values.completed)
                    return
                }
                try {
                    const queued = posthog.capture('survey sent', {
                        ...values.surveyEventProperties,
                        $survey_completed: completed,
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
