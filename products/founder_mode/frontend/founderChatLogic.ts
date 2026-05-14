import { actions, events, kea, listeners, path, reducers, selectors } from 'kea'

import type { founderChatLogicType } from './founderChatLogicType'

export type ChatAuthor = 'agent' | 'user'

export interface ChatMessage {
    author: ChatAuthor
    value: string
}

export interface CanvasSlot {
    key: string
    label: string
}

export interface CanvasNote {
    key: string
    label: string
    value: string
}

export type FounderPhase = 'chat' | 'review' | 'summarizing' | 'validation'

export interface ScriptBeat {
    /** Agent message shown after the preceding user input lands. */
    agentMessage: string
    /**
     * Slot the user's preceding reply gets written into. Named consistently
     * with the lean-canvas vocabulary so the script reads as "writing down
     * our plan as we go".
     */
    canvasSlot?: CanvasSlot
}

const slot = (key: string, label: string): CanvasSlot => ({ key, label })

const SLOT_INTRO = slot('intro', 'Where we started')
const SLOT_IDEA = slot('idea', 'Idea')
const SLOT_PAIN = slot('pain', 'Pain')
const SLOT_AUDIENCE = slot('audience', 'Who feels it')
const SLOT_CURRENT_SOLUTION = slot('currentSolution', 'How they solve it today')
const SLOT_WORST_CASE = slot('worstCase', 'If they do nothing')
const SLOT_SUCCESS = slot('success', 'Success in 6 months')
const SLOT_KILLER = slot('killerFeature', 'The "have to use this"')

export const FOUNDER_CHAT_SCRIPT: ScriptBeat[] = [
    {
        agentMessage:
            "Hey there! Let's build out the lean canvas on your idea — I'm here to help you nail this down before we start coding anything.",
    },
    {
        agentMessage: "What's the idea?",
        canvasSlot: SLOT_INTRO,
    },
    {
        agentMessage:
            "Tinder for hedgehogs. That's… very strange. But I want to hear what you're thinking. Let's start small — what pain do your future customers (or customers' hedgehogs) feel today?",
        canvasSlot: SLOT_IDEA,
    },
    {
        agentMessage:
            'Got it. And who specifically feels that pain most — the hedgehog owner, the breeder, the rescue manager?',
        canvasSlot: SLOT_PAIN,
    },
    {
        agentMessage:
            "Nice. How are they solving this today? Forums, breeder networks, word of mouth, an Excel spreadsheet someone's grandma maintains?",
        canvasSlot: SLOT_AUDIENCE,
    },
    {
        agentMessage: "Okay, let's get sharper on the problem. If they did nothing, what's the worst that happens?",
        canvasSlot: SLOT_CURRENT_SOLUTION,
    },
    {
        agentMessage: 'Good. Now flip it — what does success look like for them in 6 months if your product works?',
        canvasSlot: SLOT_WORST_CASE,
    },
    {
        agentMessage:
            'Cool. Last one for now: what would make them say "I have to use this" instead of "this is neat"?',
        canvasSlot: SLOT_SUCCESS,
    },
    {
        agentMessage:
            "That's enough to draft the lean canvas. I'll fill it in on the right as we go — we can come back and tighten any panel.",
        canvasSlot: SLOT_KILLER,
    },
]

const AGENT_REPLY_DELAY_MS = 400
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
        appendAgentReply: (value: string) => ({ value }),
        writeCanvas: (note: CanvasNote) => ({ note }),
        setDraft: (value: string) => ({ value }),
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
        agentIndex: [
            0,
            {
                appendAgentReply: (state) => state + 1,
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
    }),
    selectors({
        isChatComplete: [(s) => [s.agentIndex], (agentIndex): boolean => agentIndex >= FOUNDER_CHAT_SCRIPT.length],
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
        activeSlot: [
            (s) => [s.agentIndex],
            (agentIndex): CanvasSlot | null => FOUNDER_CHAT_SCRIPT[agentIndex]?.canvasSlot ?? null,
        ],
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
            for (const beat of FOUNDER_CHAT_SCRIPT) {
                if (beat.canvasSlot) {
                    const sample = SLOT_SAMPLES[beat.canvasSlot.key] ?? beat.canvasSlot.label
                    actions.writeCanvas({ ...beat.canvasSlot, value: sample })
                }
            }
            // Skip past the chat by advancing agentIndex to the end so activeSlot becomes null.
            const remaining = FOUNDER_CHAT_SCRIPT.length - values.agentIndex
            for (let i = 0; i < remaining; i++) {
                actions.appendAgentReply('')
            }
            actions.startReview()
        },
        sendUserMessage: async ({ value }, breakpoint) => {
            const currentIndex = values.agentIndex
            const nextBeat = FOUNDER_CHAT_SCRIPT[currentIndex]
            if (nextBeat?.canvasSlot) {
                actions.writeCanvas({ ...nextBeat.canvasSlot, value })
            }
            await breakpoint(AGENT_REPLY_DELAY_MS)
            if (nextBeat) {
                actions.appendAgentReply(nextBeat.agentMessage)
            }
            if (currentIndex + 1 >= FOUNDER_CHAT_SCRIPT.length) {
                await breakpoint(SWEEP_TO_REVIEW_DELAY_MS)
                actions.startReview()
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
    })),
    events(({ actions, values }) => ({
        afterMount: () => {
            if (values.messages.length === 0 && values.agentIndex < FOUNDER_CHAT_SCRIPT.length) {
                actions.appendAgentReply(FOUNDER_CHAT_SCRIPT[0].agentMessage)
            }
        },
    })),
])
