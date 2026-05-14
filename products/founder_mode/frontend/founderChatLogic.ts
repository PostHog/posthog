import { actions, events, kea, listeners, path, reducers, selectors } from 'kea'

import api from 'lib/api'

import type { founderChatLogicType } from './founderChatLogicType'
import { founderLogic } from './scenes/founderLogic'

export type ChatAuthor = 'agent' | 'user'

export interface ChatMessage {
    author: ChatAuthor
    value: string
}

export type CanvasSlotKey = 'idea' | 'pain' | 'audience' | 'currentSolution' | 'worstCase' | 'success' | 'killerFeature'

export interface CanvasSlot {
    key: CanvasSlotKey | string
    label: string
}

export interface CanvasNote {
    key: string
    label: string
    value: string
}

export type FounderPhase = 'chat' | 'review' | 'summarizing' | 'validation'

// Lean-canvas slot vocabulary — kept in sync with the backend (logic/cofounder_chat/schemas.py
// CanvasSlotKey literal). Order is the order the UI's pile visualization expects.
const SLOT_IDEA: CanvasSlot = { key: 'idea', label: 'Idea' }
const SLOT_PAIN: CanvasSlot = { key: 'pain', label: 'Pain' }
const SLOT_AUDIENCE: CanvasSlot = { key: 'audience', label: 'Who feels it' }
const SLOT_CURRENT_SOLUTION: CanvasSlot = { key: 'currentSolution', label: 'How they solve it today' }
const SLOT_WORST_CASE: CanvasSlot = { key: 'worstCase', label: 'If they do nothing' }
const SLOT_SUCCESS: CanvasSlot = { key: 'success', label: 'Success in 6 months' }
const SLOT_KILLER: CanvasSlot = { key: 'killerFeature', label: 'The "have to use this"' }

export const ALL_SLOTS: CanvasSlot[] = [
    SLOT_IDEA,
    SLOT_PAIN,
    SLOT_AUDIENCE,
    SLOT_CURRENT_SOLUTION,
    SLOT_WORST_CASE,
    SLOT_SUCCESS,
    SLOT_KILLER,
]

const SLOT_BY_KEY: Record<CanvasSlotKey, CanvasSlot> = {
    idea: SLOT_IDEA,
    pain: SLOT_PAIN,
    audience: SLOT_AUDIENCE,
    currentSolution: SLOT_CURRENT_SOLUTION,
    worstCase: SLOT_WORST_CASE,
    success: SLOT_SUCCESS,
    killerFeature: SLOT_KILLER,
}

// Static opening line — saves a round-trip on mount and gives JT a consistent entry point.
// Everything after this is LLM-driven from /cofounder_turn/.
const OPENING_MESSAGE = "Hey. I'm JT — your cofounder for this session. What are you building?"
const OPENING_SLOT_HINT: CanvasSlotKey = 'idea'

const SWEEP_TO_REVIEW_DELAY_MS = 1500

/** Sample answers per slot, used by the debug "jump to end" action. */
const SLOT_SAMPLES: Record<string, string> = {
    intro: 'I have an idea I want to validate.',
    idea: 'Tinder for hedgehogs',
    pain: "Hedgehog owners can't easily find compatible breeding/companion matches — it's all word of mouth and outdated forums.",
    audience: 'Mostly breeders running small operations, and individual hedgehog owners looking for companion matches.',
    currentSolution: 'Mostly Facebook groups, a few breeder-specific forums, and a lot of phone calls.',
    worstCase: 'Bad matches → wasted breeding cycles, unhappy hedgehogs, lost money.',
    success: 'They find a compatible match in days instead of months, with verified profiles.',
    killerFeature: 'Genetic compatibility scoring + verified vet records baked into every profile.',
}
const SUMMARY_BUILD_DELAY_MS = 1200
const SUMMARY_STREAM_CHUNK_MS = 18

// Backend response shape — mirrors products/founder_mode/backend/logic/cofounder_chat/schemas.py.
export interface IdeationPayload {
    what: string
    how: string
    who: string
    problem: string
}

interface TurnResponse {
    agent_message: string
    canvas_slot: { key: CanvasSlotKey; label: string; value: string } | null
    should_end_chat: boolean
    next_slot_hint: CanvasSlotKey | null
    reasoning: string
    ideation_payload: IdeationPayload | null
}

interface FounderProjectCreateResponse {
    id: string
    name: string
}

const COFOUNDER_TURN_URL = 'api/projects/@current/founder_projects/cofounder_turn/'
const FOUNDER_PROJECTS_URL = 'api/projects/@current/founder_projects/'

function buildSummary(notes: CanvasNote[]): string {
    const idea = notes.find((n) => n.key === 'idea')?.value ?? 'your idea'
    const audience = notes.find((n) => n.key === 'audience')?.value ?? 'your target users'
    const killer = notes.find((n) => n.key === 'killerFeature')?.value ?? 'a sharp wedge feature'
    return `Right, so ${idea} — aimed at ${audience}, with ${killer} as the thing that pulls people in. Sounds pretty good to me, but let's validate the idea before we go further. Let's jump into validation.`
}

export const founderChatLogic = kea<founderChatLogicType>([
    path(['products', 'founder_mode', 'founderChatLogic']),
    actions({
        sendUserMessage: (value: string) => ({ value }),
        appendAgentReply: (value: string, slotHint: CanvasSlotKey | null) => ({ value, slotHint }),
        writeCanvas: (note: CanvasNote) => ({ note }),
        setDraft: (value: string) => ({ value }),
        setThinking: (thinking: boolean) => ({ thinking }),
        setTurnError: (error: string | null) => ({ error }),
        setIdeationPayload: (payload: IdeationPayload | null) => ({ payload }),
        setValidationError: (error: string | null) => ({ error }),
        startReview: true,
        acceptCard: true,
        denyCard: true,
        editCard: (key: string) => ({ key }),
        saveEdit: (key: string, value: string) => ({ key, value }),
        cancelEdit: true,
        finishReview: true,
        appendSummaryChunk: (chunk: string) => ({ chunk }),
        startValidation: true,
        // Debug: instantly fill every slot with a sample and jump to the end of step 1.
        debugFillAndJumpToReview: true,
    }),
    reducers({
        phase: [
            'chat' as FounderPhase,
            {
                startReview: () => 'review' as FounderPhase,
                finishReview: () => 'summarizing' as FounderPhase,
                startValidation: () => 'validation' as FounderPhase,
            },
        ],
        messages: [
            [] as ChatMessage[],
            {
                sendUserMessage: (state, { value }) => [...state, { author: 'user', value } as ChatMessage],
                appendAgentReply: (state, { value }) => [...state, { author: 'agent', value } as ChatMessage],
            },
        ],
        canvasNotes: [
            [] as CanvasNote[],
            {
                writeCanvas: (state, { note }) => {
                    const existing = state.findIndex((n) => n.key === note.key)
                    if (existing === -1) {
                        return [...state, note]
                    }
                    const copy = state.slice()
                    copy[existing] = note
                    return copy
                },
                saveEdit: (state, { key, value }) => state.map((n) => (n.key === key ? { ...n, value } : n)),
            },
        ],
        // Which slot the user's NEXT answer is expected to fill. Comes from the backend's
        // `next_slot_hint` — drives the input box label + the active-card visualization.
        nextSlotHint: [
            OPENING_SLOT_HINT as CanvasSlotKey | null,
            {
                appendAgentReply: (_, { slotHint }) => slotHint,
            },
        ],
        // True while a /cofounder_turn/ call is in flight. The composer disables submit during this.
        thinking: [
            false,
            {
                setThinking: (_, { thinking }) => thinking,
                sendUserMessage: () => true,
                appendAgentReply: () => false,
            },
        ],
        turnError: [
            null as string | null,
            {
                setTurnError: (_, { error }) => error,
                sendUserMessage: () => null,
            },
        ],
        reviewIndex: [
            0,
            {
                acceptCard: (state) => state + 1,
                denyCard: (state) => state + 1,
            },
        ],
        editingKey: [
            null as string | null,
            {
                editCard: (_, { key }) => key,
                saveEdit: () => null,
                cancelEdit: () => null,
                acceptCard: () => null,
                denyCard: () => null,
            },
        ],
        draft: [
            '',
            {
                setDraft: (_, { value }) => value,
                sendUserMessage: () => '',
            },
        ],
        summaryText: [
            '',
            {
                appendSummaryChunk: (state, { chunk }) => state + chunk,
                finishReview: () => '',
            },
        ],
        // The agent's synthesized {what, how, who, problem} payload, returned when the chat
        // ends. Fed into the FounderProject row at startValidation time so the validation
        // stage runs against rich prose rather than raw slot values.
        ideationPayload: [
            null as IdeationPayload | null,
            {
                setIdeationPayload: (_, { payload }) => payload,
            },
        ],
        validationError: [
            null as string | null,
            {
                setValidationError: (_, { error }) => error,
                startValidation: () => null,
            },
        ],
    }),
    selectors({
        currentAgentMessage: [
            (s) => [s.messages],
            (messages): string | null => {
                for (let i = messages.length - 1; i >= 0; i--) {
                    if (messages[i].author === 'agent') {
                        return messages[i].value
                    }
                }
                return null
            },
        ],
        activeSlot: [(s) => [s.nextSlotHint], (hint): CanvasSlot | null => (hint ? SLOT_BY_KEY[hint] : null)],
        reviewCard: [
            (s) => [s.canvasNotes, s.reviewIndex],
            (canvasNotes, reviewIndex): CanvasNote | null => canvasNotes[reviewIndex] ?? null,
        ],
        reviewProgress: [
            (s) => [s.canvasNotes, s.reviewIndex],
            (canvasNotes, reviewIndex): { current: number; total: number } => ({
                current: Math.min(reviewIndex + 1, canvasNotes.length),
                total: canvasNotes.length,
            }),
        ],
    }),
    listeners(({ actions, values }) => ({
        debugFillAndJumpToReview: () => {
            // Debug shortcut for designer/dev iteration on the review + validation phases —
            // skips the chat entirely by writing sample values into every canvas slot. Also
            // stubs an ideationPayload so a downstream `startValidation` doesn't hit the
            // "no synthesized ideation available" branch.
            for (const slot of ALL_SLOTS) {
                const sample = SLOT_SAMPLES[slot.key] ?? slot.label
                actions.writeCanvas({ key: slot.key, label: slot.label, value: sample })
            }
            actions.setIdeationPayload({
                what: SLOT_SAMPLES.idea,
                how: SLOT_SAMPLES.killerFeature,
                who: SLOT_SAMPLES.audience,
                problem: `${SLOT_SAMPLES.pain} Today they cope via ${SLOT_SAMPLES.currentSolution}. If nothing changes: ${SLOT_SAMPLES.worstCase}. Success looks like: ${SLOT_SAMPLES.success}.`,
            })
            actions.startReview()
        },
        sendUserMessage: async ({ value }, breakpoint) => {
            // Locate the question the founder is answering — the most recent agent message.
            let lastQuestion: string | null = null
            for (let i = values.messages.length - 1; i >= 0; i--) {
                if (values.messages[i].author === 'agent') {
                    lastQuestion = values.messages[i].value
                    break
                }
            }
            // Snapshot the conversation BEFORE this user message landed — the reducer ran first
            // (sendUserMessage appended `value`), so we need to skip the last entry for the
            // payload's `messages` field. The backend reconstructs the full turn from
            // `last_question` + `user_answer` + prior `messages`.
            const priorMessages = values.messages.slice(0, -1)

            try {
                const response = await api.create<TurnResponse>(COFOUNDER_TURN_URL, {
                    user_answer: value,
                    last_question: lastQuestion,
                    messages: priorMessages,
                    canvas_notes: values.canvasNotes,
                })
                breakpoint()

                if (response.canvas_slot) {
                    actions.writeCanvas({
                        key: response.canvas_slot.key,
                        label: response.canvas_slot.label,
                        value: response.canvas_slot.value,
                    })
                }
                actions.appendAgentReply(response.agent_message, response.next_slot_hint)

                if (response.should_end_chat) {
                    // Stash the prose synthesis for use at validation handoff time. The agent is
                    // contractually required to return ideation_payload when should_end_chat is true.
                    if (response.ideation_payload) {
                        actions.setIdeationPayload(response.ideation_payload)
                    }
                    await breakpoint(SWEEP_TO_REVIEW_DELAY_MS)
                    actions.startReview()
                }
            } catch (e: any) {
                actions.setThinking(false)
                actions.setTurnError(e?.message ?? 'Cofounder turn failed')
            }
        },
        acceptCard: () => {
            if (values.reviewIndex >= values.canvasNotes.length) {
                actions.finishReview()
            }
        },
        denyCard: () => {
            if (values.reviewIndex >= values.canvasNotes.length) {
                actions.finishReview()
            }
        },
        finishReview: async (_, breakpoint) => {
            await breakpoint(SUMMARY_BUILD_DELAY_MS)
            const summary = buildSummary(values.canvasNotes)
            for (let i = 0; i < summary.length; i++) {
                await breakpoint(SUMMARY_STREAM_CHUNK_MS)
                actions.appendSummaryChunk(summary[i])
            }
        },
        startValidation: async (_, breakpoint) => {
            // Materialize a FounderProject the moment the founder commits to validation. The
            // ideation_payload (prose synthesis from the chat-end turn) becomes
            // FounderProject.ideation; the backend's perform_create auto-fires the validation
            // task. We hand the new id to founderLogic so the validation UI can pick it up.
            const payload = values.ideationPayload
            if (!payload) {
                actions.setValidationError(
                    'No synthesized ideation available — the chat ended without a payload. Re-run the chat.'
                )
                return
            }
            const ideaNote = values.canvasNotes.find((n) => n.key === 'idea')
            const name = (ideaNote?.value ?? 'Untitled idea').slice(0, 60)

            try {
                const project = await api.create<FounderProjectCreateResponse>(FOUNDER_PROJECTS_URL, {
                    name,
                    ideation: payload,
                })
                breakpoint()
                founderLogic.actions.setCurrentProjectId(project.id)
                founderLogic.actions.setCurrentStep('validation')
            } catch (e: any) {
                actions.setValidationError(e?.message ?? 'Could not create founder project')
            }
        },
    })),
    events(({ actions, values }) => ({
        afterMount: () => {
            if (values.messages.length === 0) {
                actions.appendAgentReply(OPENING_MESSAGE, OPENING_SLOT_HINT)
            }
        },
    })),
])
