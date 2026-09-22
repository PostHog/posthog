import { MakeLogicType, actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { teamLogic } from 'scenes/teamLogic'

import { mlInferenceDecisionsDecideCreate } from './generated/api'
import type { DecideRequestApi, DecideResponseApi } from './generated/api.schemas'

export type PlaygroundQuestionType = 'noul' | 'choice' | 'score'
export type QuestionsView = 'form' | 'json'

const QUESTION_TYPES: PlaygroundQuestionType[] = ['noul', 'choice', 'score']

export interface PlaygroundQuestion {
    /** Doubles as the question id on the wire, so it must stay stable while the question is edited. */
    key: string
    type: PlaygroundQuestionType
    instructions: string
    /** One line per option as `name: what it means` for a choice question, or one scale label per line for a score question. */
    criteria: string
}

export const EXAMPLE_STATE =
    'Hi, I was charged twice for my invoice this month and I need the duplicate refunded today, ' +
    'my accountant is closing the books tomorrow.'

export const EXAMPLE_QUESTIONS: PlaygroundQuestion[] = [
    { key: 'urgent', type: 'noul', instructions: 'Is this urgent?', criteria: '' },
    {
        key: 'queue',
        type: 'choice',
        instructions: 'Which team should handle this?',
        criteria: 'billing: payments, invoices, refunds\nsupport: product questions and bugs',
    },
]

export function parseCriteria(criteria: string): Record<string, string> | undefined {
    const entries = criteria
        .split('\n')
        .map((line) => line.trim())
        .filter(Boolean)
        .map((line): [string, string] => {
            const separator = line.indexOf(':')
            return separator === -1
                ? [line, line]
                : [line.slice(0, separator).trim(), line.slice(separator + 1).trim() || line.slice(0, separator).trim()]
        })
    return entries.length > 0 ? Object.fromEntries(entries) : undefined
}

function buildQuestions(questions: PlaygroundQuestion[]): DecideRequestApi['questions'] {
    return Object.fromEntries(
        questions.map((question) => [
            question.key,
            {
                type: question.type,
                instructions: question.instructions,
                ...(question.type === 'noul' ? {} : { criteria: wireCriteria(question) }),
            },
        ])
    )
}

export function parseScale(criteria: string): string[] {
    return criteria
        .split('\n')
        .map((line) => line.trim())
        .filter(Boolean)
}

function wireCriteria(question: PlaygroundQuestion): Record<string, string> | string[] | undefined {
    switch (question.type) {
        case 'noul':
            return undefined
        case 'choice':
            return parseCriteria(question.criteria)
        case 'score':
            return parseScale(question.criteria)
    }
}

export function buildDecideRequest(state: string, questions: PlaygroundQuestion[]): DecideRequestApi {
    return { state, questions: buildQuestions(questions) }
}

export function questionsToJson(questions: PlaygroundQuestion[]): string {
    return JSON.stringify(buildQuestions(questions), null, 2)
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/** Throws with a message a person can act on when the text is not a questions object. */
export function questionsFromJson(text: string): PlaygroundQuestion[] {
    const parsed: unknown = JSON.parse(text)
    if (!isRecord(parsed)) {
        throw new Error('The JSON must be an object keyed by question id')
    }
    return Object.entries(parsed).map(([key, question]) => {
        if (!isRecord(question)) {
            throw new Error(`Question "${key}" must be an object with a type and instructions`)
        }
        const { type, instructions, criteria } = question
        if (typeof type !== 'string' || !QUESTION_TYPES.includes(type as PlaygroundQuestionType)) {
            throw new Error(`Question "${key}" needs a type of noul, choice or score`)
        }
        if (typeof instructions !== 'string') {
            throw new Error(`Question "${key}" needs instructions`)
        }
        let criteriaLines: string[]
        if (criteria === undefined || criteria === null) {
            criteriaLines = []
        } else if (type === 'score' && Array.isArray(criteria)) {
            criteriaLines = criteria.map(String)
        } else if (type !== 'score' && isRecord(criteria)) {
            criteriaLines = Object.entries(criteria).map(([name, meaning]) => `${name}: ${String(meaning)}`)
        } else {
            throw new Error(
                type === 'score'
                    ? `Question "${key}" criteria must be a list of scale labels`
                    : `Question "${key}" criteria must be an object of option names to meanings`
            )
        }
        return { key, type: type as PlaygroundQuestionType, instructions, criteria: criteriaLines.join('\n') }
    })
}

function questionsJsonProblem(text: string): string | null {
    try {
        questionsFromJson(text)
        return null
    } catch (error) {
        return error instanceof Error ? error.message : String(error)
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface decisionPlaygroundLogicValues {
    currentTeamId: number | null // teamLogic
    askDisabledReason: string | null
    decision: DecideResponseApi | null
    decisionLoading: boolean
    questions: PlaygroundQuestion[]
    questionsJson: string
    questionsJsonError: string | null
    questionsView: QuestionsView
    requestBody: DecideRequestApi
    state: string
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface decisionPlaygroundLogicActions {
    addQuestion: () => {
        value: true
    }
    askDecision: () => any
    askDecisionFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    askDecisionSuccess: (
        decision: DecideResponseApi,
        payload?: any
    ) => {
        decision: DecideResponseApi
        payload?: any
    }
    removeQuestion: (key: string) => {
        key: string
    }
    setQuestions: (questions: PlaygroundQuestion[]) => {
        questions: PlaygroundQuestion[]
    }
    setQuestionsJson: (json: string) => {
        json: string
    }
    setQuestionsView: (view: QuestionsView) => {
        view: QuestionsView
    }
    setState: (state: string) => {
        state: string
    }
    updateQuestion: (
        key: string,
        patch: Partial<PlaygroundQuestion>
    ) => {
        key: string
        patch: Partial<PlaygroundQuestion>
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface decisionPlaygroundLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        requestBody: (state: string, questions: PlaygroundQuestion[]) => DecideRequestApi
        questionsJsonError: (questionsView: QuestionsView, questionsJson: string) => string | null
        askDisabledReason: (
            state: string,
            questions: PlaygroundQuestion[],
            decisionLoading: boolean,
            questionsJsonError: string | null
        ) => string | null
    }
}

export type decisionPlaygroundLogicType = MakeLogicType<
    decisionPlaygroundLogicValues,
    decisionPlaygroundLogicActions,
    Record<string, any>,
    decisionPlaygroundLogicMeta
>

export const decisionPlaygroundLogic = kea<decisionPlaygroundLogicType>([
    path(['products', 'ml_inference', 'frontend', 'decisionPlaygroundLogic']),
    connect(() => ({ values: [teamLogic, ['currentTeamId']] })),
    actions({
        setState: (state: string) => ({ state }),
        addQuestion: true,
        removeQuestion: (key: string) => ({ key }),
        updateQuestion: (key: string, patch: Partial<PlaygroundQuestion>) => ({ key, patch }),
        setQuestions: (questions: PlaygroundQuestion[]) => ({ questions }),
        setQuestionsView: (view: QuestionsView) => ({ view }),
        setQuestionsJson: (json: string) => ({ json }),
    }),
    loaders(({ values }) => ({
        decision: [
            null as DecideResponseApi | null,
            {
                askDecision: async () => {
                    if (values.currentTeamId === null) {
                        throw new Error('No project selected')
                    }
                    return await mlInferenceDecisionsDecideCreate(String(values.currentTeamId), values.requestBody)
                },
            },
        ],
    })),
    reducers({
        state: [EXAMPLE_STATE, { setState: (_, { state }) => state }],
        questions: [
            EXAMPLE_QUESTIONS,
            {
                addQuestion: (questions) => [
                    ...questions,
                    {
                        key: `question_${Date.now()}`,
                        type: 'noul' as const,
                        instructions: '',
                        criteria: '',
                    },
                ],
                removeQuestion: (questions, { key }) => questions.filter((question) => question.key !== key),
                updateQuestion: (questions, { key, patch }) =>
                    questions.map((question) => (question.key === key ? { ...question, ...patch } : question)),
                setQuestions: (_, { questions }) => questions,
            },
        ],
        questionsView: ['form' as QuestionsView, { setQuestionsView: (_, { view }) => view }],
        questionsJson: ['', { setQuestionsJson: (_, { json }) => json }],
    }),
    selectors({
        requestBody: [
            (s) => [s.state, s.questions],
            (state: string, questions: PlaygroundQuestion[]): DecideRequestApi => buildDecideRequest(state, questions),
        ],
        questionsJsonError: [
            (s) => [s.questionsView, s.questionsJson],
            (questionsView: QuestionsView, questionsJson: string): string | null =>
                questionsView === 'json' ? questionsJsonProblem(questionsJson) : null,
        ],
        askDisabledReason: [
            (s) => [s.state, s.questions, s.decisionLoading, s.questionsJsonError],
            (
                state: string,
                questions: PlaygroundQuestion[],
                decisionLoading: boolean,
                questionsJsonError: string | null
            ): string | null => {
                if (decisionLoading) {
                    return 'Asking the model'
                }
                if (questionsJsonError) {
                    return 'Fix the questions JSON first'
                }
                if (!state.trim()) {
                    return 'Enter some text to ask about'
                }
                if (questions.length === 0) {
                    return 'Add at least one question'
                }
                if (questions.some((question) => !question.instructions.trim())) {
                    return 'Every question needs some text'
                }
                if (
                    questions.some((question) => question.type === 'score' && parseScale(question.criteria).length < 2)
                ) {
                    return 'A rating scale needs at least two labels'
                }
                return null
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        setQuestionsView: ({ view }) => {
            if (view === 'json') {
                actions.setQuestionsJson(questionsToJson(values.questions))
            }
        },
        setQuestionsJson: ({ json }) => {
            if (questionsJsonProblem(json) === null) {
                actions.setQuestions(questionsFromJson(json))
            }
        },
    })),
])
