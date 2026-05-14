import { actions, kea, listeners, path, reducers, selectors } from 'kea'

import api from 'lib/api'

import type { cofounderFlowLogicType } from './cofounderFlowLogicType'

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

const FOUNDER_PROJECTS_URL = 'api/projects/@current/founder_projects/'
const projectDetailUrl = (projectId: string): string => `${FOUNDER_PROJECTS_URL}${projectId}/`

interface FounderProjectCreateResponse {
    id: string
}

/**
 * Project the flow's answers onto the {what, how, who, problem} shape that the existing
 * validation pipeline (logic/validation/schemas.py::IdeationInput) expects, plus the
 * richer cofounder-flow keys so downstream consumers see the full picture.
 */
function buildIdeationPayload(answers: CofounderAnswers): Record<string, string> {
    return {
        // Legacy fields — keep the validation pipeline happy.
        what: answers.gtmItem || answers.idea,
        how: answers.gtmPositioning || answers.idea,
        who: answers.happyPath || '',
        problem: answers.idea,
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
        submitIdea: true,
        setProjectId: (id: string | null) => ({ id }),
        setIdeaError: (error: string | null) => ({ error }),
        submitIdeaLoading: (loading: boolean) => ({ loading }),
        persistAnswers: true,
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
            },
        ],
        answers: [
            EMPTY_ANSWERS,
            {
                setAnswer: (state, { key, value }) => ({ ...state, [key]: value }),
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
            },
        ],
        ideaSubmitting: [
            false,
            {
                submitIdeaLoading: (_, { loading }) => loading,
            },
        ],
    }),
    selectors({
        currentStepKey: [(s) => [s.stepIndex], (stepIndex): StepKey => STEP_ORDER[stepIndex]],
    }),
    listeners(({ actions, values }) => ({
        submitIdea: async (_, breakpoint) => {
            const idea = values.draft.trim()
            if (!idea) {
                return
            }
            actions.setAnswer('idea', idea)
            actions.setIdeaError(null)
            actions.submitIdeaLoading(true)
            try {
                // Backend's perform_create auto-fires the validation task — no extra trigger needed.
                const nextAnswers: CofounderAnswers = { ...values.answers, idea }
                const project = await api.create<FounderProjectCreateResponse>(FOUNDER_PROJECTS_URL, {
                    name: idea.slice(0, 60),
                    ideation: buildIdeationPayload(nextAnswers),
                })
                breakpoint()
                actions.setProjectId(project.id)
                actions.submitIdeaLoading(false)
                actions.advance() // → validationLoading
            } catch (e) {
                actions.submitIdeaLoading(false)
                actions.setIdeaError(e instanceof Error ? e.message : 'Failed to start validation. Please try again.')
            }
        },
        // Persist updated answers back to the FounderProject so the saved ideation
        // tracks each new piece the founder contributes. PATCH only — no re-validation.
        setAnswer: async ({ key }, breakpoint) => {
            if (!values.projectId || key === 'idea') {
                // idea is persisted by submitIdea's create call; nothing to do here.
                return
            }
            await breakpoint(300) // light debounce in case of rapid setAnswer calls
            try {
                await api.update(projectDetailUrl(values.projectId), {
                    ideation: buildIdeationPayload(values.answers),
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
                    ideation: buildIdeationPayload(values.answers),
                })
            } catch {
                // see note above
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
    })),
])
