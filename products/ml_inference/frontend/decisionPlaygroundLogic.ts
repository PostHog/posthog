import { MakeLogicType, actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { teamLogic } from 'scenes/teamLogic'

import { mlInferenceDecisionsDecideCreate } from './generated/api'
import type { DecideRequestApi, DecideResponseApi } from './generated/api.schemas'

export type PlaygroundQuestionType = 'noul' | 'choice' | 'score'
export type QuestionsView = 'form' | 'json'

const QUESTION_TYPES: PlaygroundQuestionType[] = ['noul', 'choice', 'score']

export interface PlaygroundOption {
    key: string
    /** The option name for a choice question, or the scale label for a score question. */
    name: string
    /** What the option means; only read for choice questions. */
    meaning: string
}

export interface PlaygroundQuestion {
    /** Doubles as the question id on the wire, so it must stay stable while the question is edited. */
    key: string
    type: PlaygroundQuestionType
    instructions: string
    options: PlaygroundOption[]
}

export const EXAMPLE_STATE: string =
    "It's really important that we establish whether it's acceptableness for PostHog employees to put pineapple on pizza"

export const EXAMPLE_QUESTIONS: PlaygroundQuestion[] = [
    { key: 'acceptable', type: 'noul', instructions: 'Is this acceptable?', options: [] },
    {
        key: 'company_type',
        type: 'choice',
        instructions: 'What type of company is this about?',
        options: [
            { key: 'company_type-option-0', name: 'saas', meaning: 'sells software as a service' },
            { key: 'company_type-option-1', name: 'restaurant', meaning: 'serves food' },
            { key: 'company_type-option-2', name: 'zoo', meaning: 'keeps animals' },
        ],
    },
    {
        key: 'importance',
        type: 'score',
        instructions: 'How important is this to the author?',
        options: [
            { key: 'importance-option-0', name: 'not at all', meaning: '' },
            { key: 'importance-option-1', name: 'somewhat', meaning: '' },
            { key: 'importance-option-2', name: 'very', meaning: '' },
            { key: 'importance-option-3', name: 'critical', meaning: '' },
        ],
    },
]

function newOption(): PlaygroundOption {
    return { key: `option_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`, name: '', meaning: '' }
}

function namedOptions(question: PlaygroundQuestion): PlaygroundOption[] {
    return question.options.filter((option) => option.name.trim())
}

function wireCriteria(question: PlaygroundQuestion): Record<string, string> | string[] | null {
    switch (question.type) {
        case 'noul':
            return null
        case 'choice':
            return Object.fromEntries(
                namedOptions(question).map((option) => [
                    option.name.trim(),
                    option.meaning.trim() || option.name.trim(),
                ])
            )
        case 'score':
            return namedOptions(question).map((option) => option.name.trim())
    }
}

function buildQuestions(questions: PlaygroundQuestion[]): DecideRequestApi['questions'] {
    return Object.fromEntries(
        questions.map((question) => {
            const criteria = wireCriteria(question)
            return [
                question.key,
                {
                    type: question.type,
                    instructions: question.instructions,
                    ...(criteria === null ? {} : { criteria }),
                },
            ]
        })
    )
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

function optionsFromCriteria(questionKey: string, type: PlaygroundQuestionType, criteria: unknown): PlaygroundOption[] {
    const optionKey = (index: number): string => `${questionKey}-option-${index}`
    if (criteria === undefined || criteria === null) {
        return []
    }
    if (type === 'score' && Array.isArray(criteria)) {
        return criteria.map((label, index) => {
            if (typeof label !== 'string') {
                throw new Error(
                    `Question "${questionKey}" scale label ${index + 1} must be text, got ${JSON.stringify(label)}`
                )
            }
            return { key: optionKey(index), name: label, meaning: '' }
        })
    }
    if (type !== 'score' && isRecord(criteria)) {
        return Object.entries(criteria).map(([name, meaning], index) => {
            if (typeof meaning !== 'string') {
                throw new Error(
                    `Question "${questionKey}" option "${name}" must be text, got ${JSON.stringify(meaning)}`
                )
            }
            return { key: optionKey(index), name, meaning }
        })
    }
    throw new Error(
        type === 'score'
            ? `Question "${questionKey}" criteria must be a list of scale labels`
            : `Question "${questionKey}" criteria must be an object of option names to meanings`
    )
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
        const questionType = type as PlaygroundQuestionType
        return { key, type: questionType, instructions, options: optionsFromCriteria(key, questionType, criteria) }
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

function questionsProblem(questions: PlaygroundQuestion[]): string | null {
    if (questions.length === 0) {
        return 'Add at least one question'
    }
    if (questions.some((question) => !question.instructions.trim())) {
        return 'Every question needs some text'
    }
    if (questions.some((question) => question.type === 'choice' && namedOptions(question).length === 0)) {
        return 'A multiple choice question needs at least one option'
    }
    if (questions.some((question) => question.type === 'score' && namedOptions(question).length < 2)) {
        return 'A rating scale needs at least two labels'
    }
    const hasDuplicateNames = (question: PlaygroundQuestion): boolean => {
        const names = namedOptions(question).map((option) => option.name.trim())
        return new Set(names).size !== names.length
    }
    if (questions.some((question) => question.type !== 'noul' && hasDuplicateNames(question))) {
        return 'Option names must be unique within a question'
    }
    return null
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface decisionPlaygroundLogicValues {
    currentTeamId: number | null // teamLogic
    askDisabledReason: string | null
    askedQuestions: PlaygroundQuestion[]
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
    addOption: (questionKey: string) => {
        questionKey: string
    }
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
    removeOption: (
        questionKey: string,
        optionKey: string
    ) => {
        optionKey: string
        questionKey: string
    }
    removeQuestion: (key: string) => {
        key: string
    }
    setAskedQuestions: (questions: PlaygroundQuestion[]) => {
        questions: PlaygroundQuestion[]
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
    updateOption: (
        questionKey: string,
        optionKey: string,
        patch: Partial<PlaygroundOption>
    ) => {
        optionKey: string
        patch: Partial<PlaygroundOption>
        questionKey: string
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

function updateQuestionOptions(
    questions: PlaygroundQuestion[],
    questionKey: string,
    update: (options: PlaygroundOption[]) => PlaygroundOption[]
): PlaygroundQuestion[] {
    return questions.map((question) =>
        question.key === questionKey ? { ...question, options: update(question.options) } : question
    )
}

export const decisionPlaygroundLogic = kea<decisionPlaygroundLogicType>([
    path(['products', 'ml_inference', 'frontend', 'decisionPlaygroundLogic']),
    connect(() => ({ values: [teamLogic, ['currentTeamId']] })),
    actions({
        setState: (state: string) => ({ state }),
        addQuestion: true,
        removeQuestion: (key: string) => ({ key }),
        updateQuestion: (key: string, patch: Partial<PlaygroundQuestion>) => ({ key, patch }),
        addOption: (questionKey: string) => ({ questionKey }),
        removeOption: (questionKey: string, optionKey: string) => ({ questionKey, optionKey }),
        updateOption: (questionKey: string, optionKey: string, patch: Partial<PlaygroundOption>) => ({
            questionKey,
            optionKey,
            patch,
        }),
        setQuestions: (questions: PlaygroundQuestion[]) => ({ questions }),
        setAskedQuestions: (questions: PlaygroundQuestion[]) => ({ questions }),
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
                    { key: `question_${Date.now()}`, type: 'noul' as const, instructions: '', options: [] },
                ],
                removeQuestion: (questions, { key }) => questions.filter((question) => question.key !== key),
                updateQuestion: (questions, { key, patch }) =>
                    questions.map((question) => (question.key === key ? { ...question, ...patch } : question)),
                addOption: (questions, { questionKey }) =>
                    updateQuestionOptions(questions, questionKey, (options) => [...options, newOption()]),
                removeOption: (questions, { questionKey, optionKey }) =>
                    updateQuestionOptions(questions, questionKey, (options) =>
                        options.filter((option) => option.key !== optionKey)
                    ),
                updateOption: (questions, { questionKey, optionKey, patch }) =>
                    updateQuestionOptions(questions, questionKey, (options) =>
                        options.map((option) => (option.key === optionKey ? { ...option, ...patch } : option))
                    ),
                setQuestions: (_, { questions }) => questions,
            },
        ],
        askedQuestions: [[] as PlaygroundQuestion[], { setAskedQuestions: (_, { questions }) => questions }],
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
                return questionsProblem(questions)
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        // Answers are labelled with the questions that were asked, not the ones being edited afterwards.
        askDecision: () => {
            actions.setAskedQuestions(values.questions)
        },
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
