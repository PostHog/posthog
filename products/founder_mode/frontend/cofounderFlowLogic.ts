import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'

import api from 'lib/api'

import type { cofounderFlowLogicType } from './cofounderFlowLogicType'
import type { ReactionKey } from './reactionGifs'
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

// --- Ideation mini-chats -----------------------------------------------------
// Step 1 (ideation) is a SEQUENCE of topic-scoped mini-chats — one focused back-and-forth
// per big question (see IDEATION_TOPICS). Each topic runs until the cofounder is `satisfied`,
// crystallizes a small {key: prose} value, and the step auto-advances to the next topic
// (ideaTopicIndex++). The LAST topic doesn't auto-advance — the founder clicks "Continue to
// validation", which is when the FounderProject is created (and the validation pass
// auto-fires). Threads are ephemeral; only the crystallized values persist (onto
// FounderProject.ideation).
export interface IdeaChatMessage {
    author: 'agent' | 'user'
    value: string
    // Only set on agent messages — the posture the cofounder picked for the turn.
    // Drives the GIF reaction next to the bubble.
    reactionKey?: ReactionKey | null
}

// Mirrors products/founder_mode/backend/logic/cofounder_chat/schemas.py::TurnResponse.
interface TurnResponse {
    agent_message: string
    satisfied: boolean
    crystallized_value: Record<string, string> | null
    reasoning: string
    reaction_key: ReactionKey | null
}

const COFOUNDER_TURN_URL = 'api/projects/@current/founder_projects/cofounder_turn/'
const FOUNDER_PROJECTS_URL = 'api/projects/@current/founder_projects/'
const projectDetailUrl = (projectId: string): string => `${FOUNDER_PROJECTS_URL}${projectId}/`

// One big question of the ideation step. `key` is the backend `topic` string; `goal` tells
// the cofounder what to extract and which keys `crystallized_value` must carry. Adding or
// reordering a question only touches this list.
export interface IdeationTopic {
    key: string
    heading: string
    placeholder: string
    goal: string
}

export const IDEATION_TOPICS: IdeationTopic[] = [
    {
        key: 'idea',
        heading: "So what's your idea?",
        placeholder: 'Pitch me in a few sentences.',
        goal:
            'Get a workable articulation of what the founder is building and how it works — good ' +
            'enough to ground downstream validation. crystallized_value keys: what, how (each a ' +
            'synthesized prose string).',
    },
    {
        key: 'audience',
        heading: "Who's it for?",
        placeholder: 'The specific person or team who feels this pain most.',
        goal:
            'Pin down the specific target user or customer — who feels this pain most acutely, not ' +
            'a broad "everyone". crystallized_value keys: who (a synthesized prose string).',
    },
    {
        key: 'problem',
        heading: 'What problem does this solve for them?',
        placeholder: 'The pain, and why it matters to them.',
        goal:
            'Get the core problem clear — the pain this solves and why it matters to that user. ' +
            'crystallized_value keys: problem (a synthesized prose string).',
    },
    {
        key: 'alternatives',
        heading: 'What do they do about it today?',
        placeholder: 'Current tools, workarounds, or just living with it.',
        goal:
            'Understand the status quo — what the user does today instead (tools, workarounds, or ' +
            'nothing). crystallized_value keys: alternatives (a synthesized prose string).',
    },
    {
        key: 'why_now',
        heading: 'Why now, and why you?',
        placeholder: 'What changed, and your unfair advantage.',
        goal:
            'Get the timing and founder-fit — what makes now the moment, and why this founder is ' +
            'positioned to win. crystallized_value keys: why_now (a synthesized prose string).',
    },
    {
        key: 'business_model',
        heading: 'How does this make money?',
        placeholder: 'Who pays, for what, roughly how much. Rough is fine.',
        goal:
            'Get a rough business model — who pays, for what, and roughly how. Rough is fine; it ' +
            'refines downstream. crystallized_value keys: business_model (a synthesized prose string).',
    },
]

const LAST_IDEATION_TOPIC = IDEATION_TOPICS[IDEATION_TOPICS.length - 1]

export function ideationTopicByKey(key: string): IdeationTopic | undefined {
    return IDEATION_TOPICS.find((t) => t.key === key)
}

// crystallized_value for every finished topic, keyed by topic key.
export type CrystallizedByTopic = Record<string, Record<string, string>>

interface FounderProjectCreateResponse {
    id: string
}

/**
 * Project every crystallized ideation topic onto the {what, how, who, problem} shape the
 * validation pipeline (logic/validation/schemas.py::IdeationInput) expects, plus the richer
 * cofounder-flow keys so downstream consumers see the full picture.
 */
function buildIdeationPayload(answers: CofounderAnswers, byTopic: CrystallizedByTopic): Record<string, string> {
    const idea = byTopic.idea ?? {}
    const audience = byTopic.audience ?? {}
    const problem = byTopic.problem ?? {}
    const alternatives = byTopic.alternatives ?? {}
    const whyNow = byTopic.why_now ?? {}
    const model = byTopic.business_model ?? {}
    return {
        // Legacy fields — keep the validation pipeline happy.
        what: idea.what || answers.idea,
        how: idea.how || '',
        who: audience.who || '',
        problem: problem.problem || '',
        // Richer ideation context from the later mini-chats.
        alternatives: alternatives.alternatives || '',
        why_now: whyNow.why_now || '',
        business_model: model.business_model || '',
        // Flow-specific context from the GTM/marketing steps.
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
        // Ideation mini-chats — every action is scoped to a topic key.
        sendIdeaAnswer: (topic: string, value: string) => ({ topic, value }),
        appendIdeaMessage: (
            topic: string,
            author: 'agent' | 'user',
            value: string,
            reactionKey?: ReactionKey | null
        ) => ({ topic, author, value, reactionKey: reactionKey ?? null }),
        setCrystallizedTopic: (topic: string, value: Record<string, string>) => ({ topic, value }),
        // Edit one crystallized field of a finished topic in place (founder tweaking the
        // cofounder's synthesized answer).
        setCrystallizedField: (topic: string, key: string, value: string) => ({ topic, key, value }),
        restoreCrystallized: (byTopic: CrystallizedByTopic) => ({ byTopic }),
        // Toggle a finished topic card between read-only and editable.
        toggleTopicEditing: (topic: string) => ({ topic }),
        // Move ideation on to the next big question.
        advanceIdeaTopic: true,
        setIdeaTopicIndex: (index: number) => ({ index }),
        setFounderMode: (mode: FounderMode) => ({ mode }),
        // Wipe one topic's mini-chat back to a blank slate so the founder can restart that
        // thread. Keeps the rolled founderMode and the other topics — only this thread resets.
        resetIdeaChat: (topic: string) => ({ topic }),
        // Founder-triggered move out of ideation into validation. Creates the FounderProject
        // from every crystallized topic (which auto-fires the validation pass). Gated by the
        // UI — the button only shows once the last ideation topic is crystallized.
        proceedToValidation: true,
        // Wipe the whole flow back to a blank ideation — deletes the existing FounderProject
        // (if any) so a reload no longer resumes it. `resetFlow` is the pure state reset;
        // `startFresh` is the founder-facing action that also handles the delete.
        startFresh: true,
        resetFlow: true,
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
                resetFlow: () => STEP_ORDER.indexOf('idea'),
            },
        ],
        // Which ideation big-question is active within step 1.
        ideaTopicIndex: [
            0,
            {
                advanceIdeaTopic: (state) => Math.min(state + 1, IDEATION_TOPICS.length - 1),
                setIdeaTopicIndex: (_, { index }) => Math.max(0, Math.min(index, IDEATION_TOPICS.length - 1)),
                resetFlow: () => 0,
            },
        ],
        draft: [
            '',
            {
                setDraft: (_, { value }) => value,
                advance: () => '',
                advanceIdeaTopic: () => '',
                sendIdeaAnswer: () => '',
                resetIdeaChat: () => '',
                resetFlow: () => '',
            },
        ],
        answers: [
            EMPTY_ANSWERS,
            {
                setAnswer: (state, { key, value }) => ({ ...state, [key]: value }),
                restoreAnswers: (_, { answers }) => answers,
                resetFlow: () => EMPTY_ANSWERS,
            },
        ],
        projectId: [
            null as string | null,
            {
                setProjectId: (_, { id }) => id,
                resetFlow: () => null,
            },
        ],
        ideaError: [
            null as string | null,
            {
                setIdeaError: (_, { error }) => error,
                sendIdeaAnswer: () => null,
                advanceIdeaTopic: () => null,
                resetIdeaChat: () => null,
                resetFlow: () => null,
            },
        ],
        ideaSubmitting: [
            false,
            {
                submitIdeaLoading: (_, { loading }) => loading,
                sendIdeaAnswer: () => true,
                advanceIdeaTopic: () => false,
                resetIdeaChat: () => false,
                resetFlow: () => false,
            },
        ],
        // Each ideation topic's mini-chat thread, keyed by topic. Ephemeral, never persisted.
        ideaMessages: [
            {} as Record<string, IdeaChatMessage[]>,
            {
                sendIdeaAnswer: (state, { topic, value }) => ({
                    ...state,
                    [topic]: [...(state[topic] ?? []), { author: 'user', value }],
                }),
                appendIdeaMessage: (state, { topic, author, value, reactionKey }) => ({
                    ...state,
                    [topic]: [...(state[topic] ?? []), { author, value, reactionKey }],
                }),
                resetIdeaChat: (state, { topic }) => ({ ...state, [topic]: [] }),
                resetFlow: () => ({}),
            },
        ],
        // Each topic's crystallized {key: prose} value, keyed by topic. The whole map is
        // written to FounderProject.ideation on proceedToValidation.
        crystallizedByTopic: [
            {} as CrystallizedByTopic,
            {
                setCrystallizedTopic: (state, { topic, value }) => ({ ...state, [topic]: value }),
                setCrystallizedField: (state, { topic, key, value }) => ({
                    ...state,
                    [topic]: { ...state[topic], [key]: value },
                }),
                restoreCrystallized: (_, { byTopic }) => byTopic,
                resetIdeaChat: (state, { topic }) => {
                    const next = { ...state }
                    delete next[topic]
                    return next
                },
                resetFlow: () => ({}),
            },
        ],
        // Which finished topic cards are currently in edit mode (read-only otherwise).
        editingTopics: [
            {} as Record<string, boolean>,
            {
                toggleTopicEditing: (state, { topic }) => ({ ...state, [topic]: !state[topic] }),
                resetIdeaChat: (state, { topic }) => ({ ...state, [topic]: false }),
                resetFlow: () => ({}),
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
        // True once every ideation topic has a crystallized value — the gate for moving on.
        ideationComplete: [
            (s) => [s.crystallizedByTopic],
            (crystallizedByTopic): boolean => IDEATION_TOPICS.every((t) => !!crystallizedByTopic[t.key]),
        ],
    }),
    listeners(({ actions, values }) => ({
        // One turn of a topic's mini-chat. The user's message was already appended by the
        // reducer; we POST the thread, append the agent's reply, and — if the cofounder is
        // satisfied — store the crystallized value and advance to the next topic. The last
        // topic doesn't auto-advance; proceedToValidation (a button) does.
        sendIdeaAnswer: async ({ topic, value }, breakpoint) => {
            const answer = value.trim()
            if (!answer) {
                actions.submitIdeaLoading(false)
                return
            }
            const topicConfig = ideationTopicByKey(topic)
            if (!topicConfig) {
                actions.submitIdeaLoading(false)
                return
            }
            try {
                // The reducer appended the user message already — exclude it from the
                // payload's `messages` (the backend gets it via `user_answer`).
                const topicThread = values.ideaMessages[topic] ?? []
                const priorMessages = topicThread.slice(0, -1)
                // Reactions are one-shot per thread — tell the backend what we've already
                // used so the LLM can't repeat. Older messages (pre-feature) have no
                // reactionKey, filtered out.
                const usedReactionKeys = topicThread.map((m) => m.reactionKey).filter((k): k is ReactionKey => !!k)
                const turn = await api.create<TurnResponse>(COFOUNDER_TURN_URL, {
                    topic,
                    goal: topicConfig.goal,
                    user_answer: answer,
                    messages: priorMessages,
                    founder_mode: values.founderMode,
                    used_reaction_keys: usedReactionKeys,
                })
                breakpoint()
                actions.appendIdeaMessage(topic, 'agent', turn.agent_message, turn.reaction_key)

                if (!turn.satisfied || !turn.crystallized_value) {
                    // Cofounder wants more — the thread continues, input re-enables.
                    actions.submitIdeaLoading(false)
                    return
                }

                actions.setCrystallizedTopic(topic, turn.crystallized_value)
                // Keep answers.idea populated (a one-line summary) so later GTM steps that
                // call buildIdeationPayload still have an `idea` string to layer on.
                if (topic === 'idea') {
                    actions.setAnswer('idea', turn.crystallized_value.what ?? '')
                }
                actions.submitIdeaLoading(false)
                // Auto-advance to the next big question. The last topic stays put — the
                // founder clicks "Continue to validation" (proceedToValidation) instead.
                if (topic !== LAST_IDEATION_TOPIC.key) {
                    actions.advanceIdeaTopic()
                }
            } catch (e) {
                actions.submitIdeaLoading(false)
                actions.setIdeaError(e instanceof Error ? e.message : 'Something went wrong. Try again.')
            }
        },
        // Founder-triggered: leave ideation for validation. Creates the FounderProject from
        // every crystallized topic — perform_create auto-fires the validation task. Gated by
        // the UI: the button only shows once every ideation topic is crystallized.
        proceedToValidation: async () => {
            const byTopic = values.crystallizedByTopic
            const name = (byTopic.idea?.what || values.answers.idea || 'Untitled idea').slice(0, 60)
            try {
                const project = await api.create<FounderProjectCreateResponse>(FOUNDER_PROJECTS_URL, {
                    name,
                    ideation: buildIdeationPayload(values.answers, byTopic),
                })
                actions.setProjectId(project.id)
                founderLogic.actions.setCurrentProjectId(project.id)
                founderLogic.actions.setCurrentStep('validation')
                actions.advance()
            } catch (e) {
                actions.setIdeaError(e instanceof Error ? e.message : 'Could not start validation. Try again.')
            }
        },
        // Founder-triggered "start fresh": drop the existing FounderProject so a reload no
        // longer resumes it, then reset the flow back to a blank ideation.
        startFresh: async () => {
            const projectId = founderLogic.values.currentProjectId
            if (projectId) {
                try {
                    await api.delete(projectDetailUrl(projectId))
                } catch {
                    // Best-effort — reset the local flow even if the delete fails.
                }
            }
            founderLogic.actions.setCurrentProjectId(null)
            founderLogic.actions.setCurrentStep('ideation')
            actions.resetFlow()
            actions.setFounderMode(rollFounderMode())
        },
        // Founder edited a crystallized field on a finished topic card. If the project is
        // already committed (resumed flow), persist the tweak; otherwise it lives in memory
        // until proceedToValidation commits it.
        setCrystallizedField: async (_, breakpoint) => {
            if (!values.projectId) {
                return
            }
            await breakpoint(400) // debounce keystrokes
            try {
                await api.update(projectDetailUrl(values.projectId), {
                    ideation: buildIdeationPayload(values.answers, values.crystallizedByTopic),
                })
            } catch {
                // Best-effort persistence.
            }
        },
        // Persist updated answers back to the FounderProject so the saved ideation tracks
        // each new piece the founder contributes. PATCH only — no re-validation.
        setAnswer: async ({ key }, breakpoint) => {
            if (!values.projectId || key === 'idea') {
                // idea is committed by proceedToValidation's create call; nothing to do here.
                return
            }
            await breakpoint(300) // light debounce in case of rapid setAnswer calls
            try {
                await api.update(projectDetailUrl(values.projectId), {
                    ideation: buildIdeationPayload(values.answers, values.crystallizedByTopic),
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
                    ideation: buildIdeationPayload(values.answers, values.crystallizedByTopic),
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
                    idea: ideation.idea || ideation.what || ideation.problem || '',
                    gtmItem: ideation.gtm_item || '',
                    gtmPositioning: ideation.gtm_positioning || '',
                    happyPath: ideation.happy_path || '',
                    marketing: ideation.marketing || '',
                }
                actions.restoreAnswers(restored)
                // Reverse-map the saved ideation payload back into per-topic crystallized
                // values so a resumed flow shows ideation as already complete.
                actions.restoreCrystallized({
                    idea: { what: ideation.what || '', how: ideation.how || '' },
                    audience: { who: ideation.who || '' },
                    problem: { problem: ideation.problem || '' },
                    alternatives: { alternatives: ideation.alternatives || '' },
                    why_now: { why_now: ideation.why_now || '' },
                    business_model: { business_model: ideation.business_model || '' },
                })
                actions.setIdeaTopicIndex(IDEATION_TOPICS.length - 1)
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
