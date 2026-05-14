import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'

import api from 'lib/api'

import type { cofounderFlowLogicType } from './cofounderFlowLogicType'
import { founderLogic } from './scenes/founderLogic'

export type StepKey =
    | 'intro'
    | 'idea'
    | 'validationLoading'
    | 'validationOutput'
    | 'gtmLoading'
    | 'gtmItem'
    | 'gtmPositioning'
    | 'happyPath'
    | 'marketing'
    | 'done'

export const STEP_ORDER: StepKey[] = [
    'intro',
    'idea',
    'validationLoading',
    'validationOutput',
    'gtmLoading',
    'gtmItem',
    'gtmPositioning',
    'happyPath',
    'marketing',
    'done',
]

export interface CofounderAnswers {
    idea: string
    gtmItem: string
    gtmPositioning: string
    happyPath: string
    marketing: string
}

const EMPTY_ANSWERS: CofounderAnswers = {
    idea: '',
    gtmItem: '',
    gtmPositioning: '',
    happyPath: '',
    marketing: '',
}

// --- Cofounder mode ----------------------------------------------------------
// Which half of the founding team the cofounder plays. A solo founder is usually missing
// one — the cofounder complements them. Rolled 50/50 on mount (no picker for v1; there's a
// small toggle on the idea step if the draw doesn't fit). Sent with every /cofounder_turn/.
export type FounderMode = 'technical_cofounder' | 'commercial_cofounder'

function rollFounderMode(): FounderMode {
    return Math.random() < 0.5 ? 'technical_cofounder' : 'commercial_cofounder'
}

// --- Idea mini-chat ----------------------------------------------------------
// The idea step is a topic-scoped mini-chat: the cofounder probes with follow-ups until it
// has a crisp {what, how, who, problem}, then `satisfied` flips and we commit + advance.
// Threads are ephemeral — only the crystallized ideation persists (onto the FounderProject).
export interface IdeaChatMessage {
    author: 'agent' | 'user'
    value: string
}

export interface CrystallizedIdeation {
    what: string
    how: string
    who: string
    problem: string
}

// Mirrors products/founder_mode/backend/logic/cofounder_chat/schemas.py::TurnResponse.
interface TurnResponse {
    agent_message: string
    satisfied: boolean
    crystallized_value: Record<string, string> | null
    reasoning: string
}

const COFOUNDER_TURN_URL = 'api/projects/@current/founder_projects/cofounder_turn/'
const FOUNDER_PROJECTS_URL = 'api/projects/@current/founder_projects/'
const projectDetailUrl = (projectId: string): string => `${FOUNDER_PROJECTS_URL}${projectId}/`

// The idea topic's goal — tells the backend agent what to extract and which keys the
// crystallized value must carry. Topic-scoped: later steps would pass their own goal.
const IDEA_GOAL =
    "Get a workable articulation of the founder's idea: what they are building, how it works, who it is for, " +
    'and the problem it solves — good enough to ground a competitor-research validation pass. It does not ' +
    'need to be airtight; the founder refines it downstream. crystallized_value keys: what, how, who, problem ' +
    '(each a synthesized prose string).'

interface FounderProjectCreateResponse {
    id: string
}

/**
 * Project the flow's answers onto the {what, how, who, problem} shape that the existing
 * validation pipeline (logic/validation/schemas.py::IdeationInput) expects, plus the
 * richer cofounder-flow keys so downstream consumers see the full picture.
 *
 * When the idea mini-chat has produced a `crystallized` ideation, its fields take priority
 * for what/how/who/problem — they're the agent's synthesized prose, richer than the raw
 * step answers.
 */
function buildIdeationPayload(
    answers: CofounderAnswers,
    crystallized: CrystallizedIdeation | null
): Record<string, string> {
    return {
        // Legacy fields — keep the validation pipeline happy. Crystallized ideation wins.
        what: crystallized?.what || answers.gtmItem || answers.idea,
        how: crystallized?.how || answers.gtmPositioning || answers.idea,
        who: crystallized?.who || answers.happyPath || '',
        problem: crystallized?.problem || answers.idea,
        // Flow-specific richer context.
        idea: answers.idea,
        gtm_item: answers.gtmItem,
        gtm_positioning: answers.gtmPositioning,
        happy_path: answers.happyPath,
        marketing: answers.marketing,
    }
}

const GTM_LOADING_DURATION_MS = 3000

export const cofounderFlowLogic = kea<cofounderFlowLogicType>([
    path(['products', 'founder_mode', 'cofounderFlowLogic']),
    actions({
        advance: true,
        goToStep: (key: StepKey) => ({ key }),
        setDraft: (value: string) => ({ value }),
        setAnswer: (key: keyof CofounderAnswers, value: string) => ({ key, value }),
        setProjectId: (id: string | null) => ({ id }),
        setIdeaError: (error: string | null) => ({ error }),
        submitIdeaLoading: (loading: boolean) => ({ loading }),
        persistAnswers: true,
        loadExistingIdeation: true,
        restoreAnswers: (answers: CofounderAnswers) => ({ answers }),
        // Idea mini-chat
        sendIdeaAnswer: (value: string) => ({ value }),
        appendIdeaMessage: (author: 'agent' | 'user', value: string) => ({ author, value }),
        setCrystallizedIdeation: (ideation: CrystallizedIdeation) => ({ ideation }),
        setFounderMode: (mode: FounderMode) => ({ mode }),
        // Wipe the idea mini-chat back to a blank slate so the founder can start the
        // conversation over. Keeps the rolled founderMode — only the thread resets.
        resetIdeaChat: true,
    }),
    reducers({
        stepIndex: [
            0,
            {
                advance: (state) => Math.min(state + 1, STEP_ORDER.length - 1),
                goToStep: (_, { key }) => {
                    const idx = STEP_ORDER.indexOf(key)
                    return idx === -1 ? 0 : idx
                },
            },
        ],
        draft: [
            '',
            {
                setDraft: (_, { value }) => value,
                advance: () => '',
                sendIdeaAnswer: () => '',
                resetIdeaChat: () => '',
            },
        ],
        answers: [
            EMPTY_ANSWERS,
            {
                setAnswer: (state, { key, value }) => ({ ...state, [key]: value }),
                restoreAnswers: (_, { answers }) => answers,
            },
        ],
        projectId: [
            null as string | null,
            {
                setProjectId: (_, { id }) => id,
            },
        ],
        ideaError: [
            null as string | null,
            {
                setIdeaError: (_, { error }) => error,
                sendIdeaAnswer: () => null,
                resetIdeaChat: () => null,
            },
        ],
        ideaSubmitting: [
            false,
            {
                submitIdeaLoading: (_, { loading }) => loading,
                sendIdeaAnswer: () => true,
                resetIdeaChat: () => false,
            },
        ],
        // The idea step's mini-chat thread. Starts empty — the step's heading ("So what's
        // your idea?") is the cofounder's implicit opening question. User answers append
        // here; agent follow-ups append on appendIdeaMessage. Ephemeral, never persisted.
        ideaMessages: [
            [] as IdeaChatMessage[],
            {
                sendIdeaAnswer: (state, { value }) => [...state, { author: 'user', value }],
                appendIdeaMessage: (state, { author, value }) => [...state, { author, value }],
                resetIdeaChat: () => [],
            },
        ],
        // The agent's synthesized {what, how, who, problem} once the idea mini-chat is satisfied.
        crystallizedIdeation: [
            null as CrystallizedIdeation | null,
            {
                setCrystallizedIdeation: (_, { ideation }) => ideation,
                resetIdeaChat: () => null,
            },
        ],
        // Rolled 50/50 on mount; sent with every /cofounder_turn/ so the backend injects the
        // matching mode block into the cofounder's system prompt.
        founderMode: [
            'commercial_cofounder' as FounderMode,
            {
                setFounderMode: (_, { mode }) => mode,
            },
        ],
    }),
    selectors({
        currentStepKey: [(s) => [s.stepIndex], (stepIndex): StepKey => STEP_ORDER[stepIndex]],
    }),
    listeners(({ actions, values }) => ({
        // One turn of the idea mini-chat. The user's message was already appended by the
        // reducer; we POST the thread, append the agent's reply, and — if the cofounder is
        // satisfied — commit the crystallized ideation as a FounderProject and advance.
        sendIdeaAnswer: async ({ value }, breakpoint) => {
            const answer = value.trim()
            if (!answer) {
                actions.submitIdeaLoading(false)
                return
            }
            try {
                // The reducer appended the user message already — exclude it from the
                // payload's `messages` (the backend gets it via `user_answer`).
                const priorMessages = values.ideaMessages.slice(0, -1)
                const turn = await api.create<TurnResponse>(COFOUNDER_TURN_URL, {
                    topic: 'idea',
                    goal: IDEA_GOAL,
                    user_answer: answer,
                    messages: priorMessages,
                    founder_mode: values.founderMode,
                })
                breakpoint()
                actions.appendIdeaMessage('agent', turn.agent_message)

                if (!turn.satisfied || !turn.crystallized_value) {
                    // Cofounder wants more — the thread continues, input re-enables.
                    actions.submitIdeaLoading(false)
                    return
                }

                // Satisfied: commit the crystallized ideation and move to validation.
                const crystallized: CrystallizedIdeation = {
                    what: turn.crystallized_value.what ?? '',
                    how: turn.crystallized_value.how ?? '',
                    who: turn.crystallized_value.who ?? '',
                    problem: turn.crystallized_value.problem ?? '',
                }
                actions.setCrystallizedIdeation(crystallized)
                // Keep answers.idea populated (a one-line summary) so later GTM steps that
                // call buildIdeationPayload still have an `idea` string to layer on.
                actions.setAnswer('idea', crystallized.what)

                const nextAnswers: CofounderAnswers = { ...values.answers, idea: crystallized.what }
                // Backend's perform_create auto-fires the validation task — no extra trigger.
                const project = await api.create<FounderProjectCreateResponse>(FOUNDER_PROJECTS_URL, {
                    name: crystallized.what.slice(0, 60) || 'Untitled idea',
                    ideation: buildIdeationPayload(nextAnswers, crystallized),
                })
                breakpoint()
                actions.setProjectId(project.id)
                founderLogic.actions.setCurrentProjectId(project.id)
                founderLogic.actions.setCurrentStep('validation')
                actions.submitIdeaLoading(false)
                actions.advance() // → validationLoading
            } catch (e) {
                actions.submitIdeaLoading(false)
                actions.setIdeaError(e instanceof Error ? e.message : 'Something went wrong. Try again.')
            }
        },
        // Persist updated answers back to the FounderProject so the saved ideation tracks
        // each new piece the founder contributes. PATCH only — no re-validation.
        setAnswer: async ({ key }, breakpoint) => {
            if (!values.projectId || key === 'idea') {
                // idea is committed by sendIdeaAnswer's create call; nothing to do here.
                return
            }
            await breakpoint(300) // light debounce in case of rapid setAnswer calls
            try {
                await api.update(projectDetailUrl(values.projectId), {
                    ideation: buildIdeationPayload(values.answers, values.crystallizedIdeation),
                })
            } catch {
                // Best-effort persistence — silent failure is fine for now; the flow keeps
                // running off in-memory state and we can revisit error handling later.
            }
        },
        persistAnswers: async () => {
            if (!values.projectId) {
                return
            }
            try {
                await api.update(projectDetailUrl(values.projectId), {
                    ideation: buildIdeationPayload(values.answers, values.crystallizedIdeation),
                })
            } catch {
                // see note above
            }
        },
        loadExistingIdeation: async () => {
            const projectId = founderLogic.values.currentProjectId
            if (!projectId) {
                return
            }
            try {
                const project = await api.get<{
                    id: string
                    ideation: Record<string, string> | null
                }>(`${FOUNDER_PROJECTS_URL}${projectId}/`)
                const ideation = project.ideation
                if (!ideation) {
                    return
                }
                actions.setProjectId(project.id)
                const restored: CofounderAnswers = {
                    idea: ideation.idea || ideation.problem || '',
                    gtmItem: ideation.gtm_item || '',
                    gtmPositioning: ideation.gtm_positioning || '',
                    happyPath: ideation.happy_path || '',
                    marketing: ideation.marketing || '',
                }
                actions.restoreAnswers(restored)
                actions.setDraft(restored.idea)
                actions.goToStep('idea')
            } catch {
                // Fall through to fresh flow
            }
        },

        // Auto-advance the GTM loading step after a fixed delay so the user
        // gets a beat of "we're preparing the next thing" before the question lands.
        advance: async (_, breakpoint) => {
            if (values.currentStepKey === 'gtmLoading') {
                await breakpoint(GTM_LOADING_DURATION_MS)
                actions.advance()
            }
        },

        [founderLogic.actionTypes.advanceStep]: ({ currentStep }: { currentStep: string }) => {
            if (currentStep === 'ideation' && founderLogic.values.currentProjectId) {
                actions.loadExistingIdeation()
            }
        },
    })),

    afterMount(({ actions }) => {
        // Roll the cofounder's mode once per session.
        actions.setFounderMode(rollFounderMode())
        // Resume an in-progress project's ideation if one already exists for this team.
        if (founderLogic.values.currentProjectId) {
            actions.loadExistingIdeation()
        }
    }),
])
