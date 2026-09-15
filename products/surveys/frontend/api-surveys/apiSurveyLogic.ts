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

import { SurveyAnswer, isSurveyAnswerValid, supportsApiSurvey } from './surveyQuestions'

export type ApiSurveyClient = Pick<typeof posthog, 'getSurveys' | 'capture' | 'get_session_replay_url'>

export interface ApiSurveyProps {
    surveyId: string
    instanceId: string
    client?: ApiSurveyClient
    context?: Record<string, unknown>
    includeReplay?: boolean
}

export interface apiSurveyLogicValues {
    survey: Survey | null
    loading: boolean
    error: string
    answers: Record<string, SurveyAnswer>
    submitting: boolean
    completed: boolean
    submissionId: string
    eventProperties: Record<string, unknown>
    canSubmit: boolean
}

export interface apiSurveyLogicActions {
    loadSurvey: () => { value: true }
    surveyLoaded: (
        survey: Survey | null,
        submissionId: string,
        context: Record<string, unknown>
    ) => { survey: Survey | null; submissionId: string; context: Record<string, unknown> }
    setError: (error: string) => { error: string }
    setAnswer: (questionId: string, answer: SurveyAnswer) => { questionId: string; answer: SurveyAnswer }
    toggleChoice: (
        questionId: string,
        choice: string,
        checked: boolean
    ) => { questionId: string; choice: string; checked: boolean }
    submit: () => { value: true }
    responseQueued: () => { value: true }
}

export type apiSurveyLogicType = MakeLogicType<apiSurveyLogicValues, apiSurveyLogicActions, ApiSurveyProps>

export const apiSurveyLogic: LogicWrapper<apiSurveyLogicType> = kea<apiSurveyLogicType>([
    props({} as ApiSurveyProps),
    key(({ surveyId, instanceId }) => JSON.stringify([surveyId, instanceId])),
    path((key) => ['products', 'surveys', 'frontend', 'api-surveys', 'apiSurveyLogic', key]),
    actions({
        loadSurvey: true,
        surveyLoaded: (survey: Survey | null, submissionId: string, context: Record<string, unknown>) => ({
            survey,
            submissionId,
            context,
        }),
        setError: (error: string) => ({ error }),
        setAnswer: (questionId: string, answer: SurveyAnswer) => ({ questionId, answer }),
        toggleChoice: (questionId: string, choice: string, checked: boolean) => ({ questionId, choice, checked }),
        submit: true,
        responseQueued: true,
    }),
    reducers({
        survey: [null as Survey | null, { surveyLoaded: (_, { survey }) => survey }],
        loading: [true, { loadSurvey: () => true, surveyLoaded: () => false, setError: () => false }],
        error: ['', { loadSurvey: () => '', submit: () => '', setError: (_, { error }) => error }],
        answers: [
            {} as Record<string, SurveyAnswer>,
            { setAnswer: (state, { questionId, answer }) => ({ ...state, [questionId]: answer }) },
        ],
        submitting: [false, { submit: () => true, responseQueued: () => false, setError: () => false }],
        completed: [false, { responseQueued: () => true }],
        submissionId: ['', { surveyLoaded: (_, { submissionId }) => submissionId }],
        eventProperties: [
            {} as Record<string, unknown>,
            {
                surveyLoaded: (_, { survey, submissionId, context }) => ({
                    ...context,
                    $survey_id: survey?.id,
                    $survey_name: survey?.name,
                    $survey_submission_id: submissionId,
                    $survey_questions: survey?.questions.map(({ id, question }) => ({ id, question })),
                }),
            },
        ],
    }),
    selectors({
        canSubmit: [
            (s) => [s.survey, s.answers, s.completed],
            (survey: Survey | null, answers: Record<string, SurveyAnswer>, completed: boolean): boolean =>
                !!survey &&
                !completed &&
                survey.questions.every((question) => isSurveyAnswerValid(question, answers[question.id!])),
        ],
    }),
    listeners(({ actions, values, props, cache }) => ({
        loadSurvey: async (_, breakpoint) => {
            if (values.survey) {
                actions.setError('This response is already in progress.')
                return
            }
            const client = props.client ?? posthog
            const context = getContext()
            const manager = cache.disposables
            try {
                const surveys = await new Promise<Survey[]>((resolve) => client.getSurveys(resolve))
                if (manager.isDisposed || getContext() !== context) {
                    return
                }
                await breakpoint()
                const survey = surveys.find((survey) => survey.id === props.surveyId && survey.type === SurveyType.API)
                if (survey && !supportsApiSurvey(survey)) {
                    actions.setError('This survey uses questions this form does not support yet.')
                    return
                }
                const metadata = structuredClone(
                    Object.fromEntries(
                        Object.entries(props.context ?? {}).filter(([key]) => !key.startsWith('$survey_'))
                    )
                )
                if (props.includeReplay) {
                    metadata.sessionRecordingUrl = client.get_session_replay_url({ withTimestamp: true }) ?? null
                }
                actions.surveyLoaded(survey ? structuredClone(survey) : null, crypto.randomUUID(), metadata)
            } catch {
                breakpoint()
                if (!manager.isDisposed && getContext() === context) {
                    actions.setError('Couldn’t load this survey. Try again.')
                }
            }
        },
        surveyLoaded: ({ survey }) => {
            if (survey) {
                ;(props.client ?? posthog).capture('survey shown', values.eventProperties)
            }
        },
        toggleChoice: ({ questionId, choice, checked }) => {
            const previous = values.answers[questionId]
            const selected = Array.isArray(previous) ? previous : []
            actions.setAnswer(
                questionId,
                checked ? [...new Set([...selected, choice])] : selected.filter((value) => value !== choice)
            )
        },
        submit: () => {
            if (values.completed) {
                actions.responseQueued()
                return
            }
            if (!values.canSubmit || !values.survey) {
                actions.setError('Check your answers before sending the response.')
                return
            }
            try {
                const responses = Object.fromEntries(
                    values.survey.questions.flatMap(({ id }) => {
                        const answer = values.answers[id!]
                        const value = typeof answer === 'string' ? answer.trim() : answer
                        return value?.length ? [[`$survey_response_${id}`, value]] : []
                    })
                )
                const queued = (props.client ?? posthog).capture('survey sent', {
                    ...values.eventProperties,
                    ...responses,
                    $survey_completed: true,
                })
                if (!queued) {
                    throw new Error('not queued')
                }
                actions.responseQueued()
            } catch {
                actions.setError('Couldn’t send your response. Your answers are still here. Try again.')
            }
        },
    })),
    afterMount(({ actions }) => actions.loadSurvey()),
])
