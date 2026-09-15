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
import posthog, { Survey, SurveyType } from 'posthog-js'

import { MCPFeedbackContext, MCPAnalyticsFeedbackPromptConfig, MCP_ANALYTICS_USEFULNESS_SURVEY_ID } from './constants'
import { FeedbackAnswer, isFeedbackAnswerValid, supportsFeedbackSurvey } from './surveyQuestions'

export const FEEDBACK_PROMPT_DELAY_MS = 30_000
export const FEEDBACK_PROMPT_COOLDOWN_MS = 30 * 24 * 60 * 60 * 1000

export interface MCPAnalyticsFeedbackLogicProps {
    userId: string
    contextKey: string
    prompt: MCPAnalyticsFeedbackPromptConfig
    isImpersonated: boolean
    context?: MCPFeedbackContext
}

export interface mcpAnalyticsFeedbackLogicValues {
    prompt: MCPAnalyticsFeedbackPromptConfig
    context: MCPFeedbackContext | null
    surveyEventProperties: Record<string, unknown>
    visible: boolean
    lastPromptAt: number
    survey: Survey | null
    submissionId: string
    answer: string
    detail: string
    responses: Record<string, FeedbackAnswer>
    voiceQuestionIds: string[]
    voiceAvailable: boolean
    voiceAssigned: boolean
    replayUrl: string | null
    canComplete: boolean
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
    setResponse: (
        questionId: string,
        answer: FeedbackAnswer,
        voice?: boolean
    ) => { questionId: string; answer: FeedbackAnswer; voice: boolean }
    submitResponse: (answer: string, completed: boolean) => { answer: string; completed: boolean }
    responseQueued: (answer: string, completed: boolean) => { answer: string; completed: boolean }
    responseFailed: () => { value: true }
}

export type mcpAnalyticsFeedbackLogicType = MakeLogicType<
    mcpAnalyticsFeedbackLogicValues,
    mcpAnalyticsFeedbackLogicActions,
    MCPAnalyticsFeedbackLogicProps
>

export const mcpAnalyticsFeedbackLogic: LogicWrapper<mcpAnalyticsFeedbackLogicType> =
    kea<mcpAnalyticsFeedbackLogicType>([
        props({} as MCPAnalyticsFeedbackLogicProps),
        key(({ userId, contextKey, prompt }) =>
            JSON.stringify([
                userId,
                prompt.entryPoint,
                contextKey,
                prompt.surveyId ?? MCP_ANALYTICS_USEFULNESS_SURVEY_ID,
            ])
        ),
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
            setResponse: (questionId: string, answer: FeedbackAnswer, voice = false) => ({ questionId, answer, voice }),
            submitResponse: (answer: string, completed: boolean) => ({ answer, completed }),
            responseQueued: (answer: string, completed: boolean) => ({ answer, completed }),
            responseFailed: true,
        }),
        reducers(({ props }) => ({
            context: [
                null as MCPFeedbackContext | null,
                { showPrompt: () => (props.context ? { ...props.context } : null) },
            ],
            prompt: [props.prompt, { showPrompt: () => ({ ...props.prompt }) }],
            visible: [false, { showPrompt: () => true, dismissPrompt: () => false }],
            survey: [null as Survey | null, { showPrompt: (_, { survey }) => structuredClone(survey) }],
            voiceAssigned: [
                false,
                { showPrompt: () => posthog.getFeatureFlag('mcp-analytics-feedback-voice') === true },
            ],
            voiceAvailable: [
                false,
                {
                    showPrompt: () =>
                        posthog.getFeatureFlag('mcp-analytics-feedback-voice') === true &&
                        typeof MediaRecorder !== 'undefined' &&
                        !!navigator.mediaDevices?.getUserMedia,
                },
            ],
            replayUrl: [
                null as string | null,
                { showPrompt: () => posthog.get_session_replay_url?.({ withTimestamp: true }) ?? null },
            ],
            responses: [
                {} as Record<string, FeedbackAnswer>,
                { setResponse: (state, { questionId, answer }) => ({ ...state, [questionId]: answer }) },
            ],
            voiceQuestionIds: [
                [] as string[],
                {
                    setResponse: (state, { questionId, voice }) =>
                        voice && !state.includes(questionId) ? [...state, questionId] : state,
                },
            ],
            submissionId: ['', { showPrompt: (_, { submissionId }) => submissionId }],
            answer: ['', { responseQueued: (_, { answer }) => answer }],
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
            detail: [
                (s) => [s.survey, s.responses],
                (survey: Survey | null, responses: Record<string, FeedbackAnswer>): string => {
                    const value = responses[survey?.questions[1]?.id ?? '']
                    return typeof value === 'string' ? value : ''
                },
            ],
            canComplete: [
                (s) => [s.survey, s.responses],
                (survey: Survey | null, responses: Record<string, FeedbackAnswer>): boolean =>
                    !!survey &&
                    survey.questions
                        .slice(1)
                        .every((question) => isFeedbackAnswerValid(question, responses[question.id!])),
            ],
            surveyEventProperties: [
                (s) => [s.survey, s.submissionId, s.prompt, s.voiceAvailable, s.replayUrl, s.voiceAssigned, s.context],
                (
                    survey: Survey | null,
                    submissionId: string,
                    prompt: MCPAnalyticsFeedbackPromptConfig,
                    voiceAvailable: boolean,
                    replayUrl: string | null,
                    voiceAssigned: boolean,
                    context: MCPFeedbackContext | null
                ): Record<string, unknown> => ({
                    feedback_surface: 'mcp_analytics',
                    ...(context
                        ? {
                              feedback_visible_tool_calls: context.visibleToolCalls,
                              feedback_visible_errors: context.visibleErrors,
                          }
                        : {}),
                    feedback_voice_available: voiceAvailable,
                    feedback_voice_variant: voiceAssigned ? 'voice' : 'text',
                    sessionRecordingUrl: replayUrl,
                    feedback_entry_point: prompt.entryPoint,
                    mcp_analytics_tab: prompt.tab,
                    feedback_question_version: prompt.version,
                    feedback_question: prompt.question ?? survey?.questions[0]?.question,
                    feedback_followup_question: prompt.followUpQuestion ?? survey?.questions[1]?.question,
                    $survey_id: survey?.id,
                    $survey_name: survey?.name,
                    $survey_submission_id: submissionId,
                    $survey_questions: survey?.questions.map(({ id, question }, index) => ({
                        id,
                        question:
                            (index === 0 ? prompt.question : index === 1 ? prompt.followUpQuestion : undefined) ??
                            question,
                    })),
                }),
            ],
        }),
        listeners(({ actions, values, props, cache }) => ({
            setDetail: ({ detail }) => {
                const questionId = values.survey?.questions[1]?.id
                if (questionId) {
                    actions.setResponse(questionId, detail)
                }
            },
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
                    !supportsFeedbackSurvey(survey) ||
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
                    !supportsFeedbackSurvey(survey) ||
                    (completed && !values.canComplete) ||
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
                        feedback_input_method: values.voiceQuestionIds.length ? 'voice' : 'text',
                        feedback_voice_question_ids: values.voiceQuestionIds,
                        ...(completed
                            ? Object.fromEntries(
                                  survey.questions.slice(1).flatMap(({ id }) => {
                                      const response = values.responses[id!]
                                      const value = typeof response === 'string' ? response.trim() : response
                                      return value?.length ? [[`$survey_response_${id}`, value]] : []
                                  })
                              )
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
        afterMount(({ actions, cache, props }) => {
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
                                                surveys.find(
                                                    ({ id }) =>
                                                        id ===
                                                        (props.prompt.surveyId ?? MCP_ANALYTICS_USEFULNESS_SURVEY_ID)
                                                ) ?? null
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
