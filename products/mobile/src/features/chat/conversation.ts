import type { ConversationEvent, ConversationMessage } from '@/api/conversations'

import { stripInjectedContext } from './contextPrompt'
import type { AssistantChatEntry, ChatEntry, FailureChatEntry, LinkChatEntry, UserChatEntry } from './types'

export const GENERIC_FAILURE = 'Something went wrong. Try again.'
export const EMPTY_REPLY_FAILURE = 'No reply came back. Try again.'
const APPROVAL_TEXT = 'PostHog AI needs your approval to continue. Approve or reject it in PostHog.'

export interface ChatThreadState {
    entries: ChatEntry[]
    title: string | null
    // Set before reattaching to a running turn. The server replays that turn from its start, so the first replayed
    // event cuts the thread back to the user's message and the replay rebuilds it.
    replayPending: boolean
    nextKey: number
}

export type ChatThreadAction =
    | { type: 'sent'; text: string; traceId: string; at: string }
    | { type: 'event'; event: ConversationEvent; at: string }
    | { type: 'resuming' }
    | { type: 'retrying'; traceId: string }
    | { type: 'withdrawn' }
    | { type: 'finished'; at: string }
    | { type: 'stopped' }
    | { type: 'failed'; message: string; at: string }
    | { type: 'hydrated'; title: string | null; messages: ConversationMessage[]; at: string }
    | { type: 'reset' }

export const initialChatThread: ChatThreadState = { entries: [], title: null, replayPending: false, nextKey: 0 }

/** Streamed snapshots carry `temp-N` ids (or none); final messages carry a UUID. */
function isTempId(id: string | undefined): boolean {
    return !id || id.startsWith('temp-')
}

function lastUserIndex(entries: ChatEntry[]): number {
    for (let index = entries.length - 1; index >= 0; index -= 1) {
        if (entries[index]?.kind === 'user') {
            return index
        }
    }
    return -1
}

function replaceAt(entries: ChatEntry[], index: number, entry: ChatEntry): ChatEntry[] {
    return [...entries.slice(0, index), entry, ...entries.slice(index + 1)]
}

function takeKey(state: ChatThreadState): [string, ChatThreadState] {
    return [`local-${state.nextKey}`, { ...state, nextKey: state.nextKey + 1 }]
}

function settle(entries: ChatEntry[]): ChatEntry[] {
    return entries.map((entry) => {
        if (entry.kind !== 'assistant') {
            return entry.status === 'loading' ? { ...entry, status: 'completed' } : entry
        }
        const { progress: _progress, ...rest } = entry
        return { ...rest, status: entry.status === 'loading' ? 'completed' : entry.status }
    })
}

function appendFailure(state: ChatThreadState, text: string, at: string, id?: string): ChatThreadState {
    const entries = settle(state.entries)
    const last = entries[entries.length - 1]
    if (last?.kind === 'failure') {
        return { ...state, entries: replaceAt(entries, entries.length - 1, { ...last, text }) }
    }
    const [key, next] = takeKey(state)
    const failure: FailureChatEntry = {
        kind: 'failure',
        role: 'assistant',
        key,
        id: id ?? key,
        text,
        at,
        status: 'error',
    }
    return { ...next, entries: [...entries, failure] }
}

function upsertById(
    state: ChatThreadState,
    id: string | undefined,
    build: (key: string) => ChatEntry
): ChatThreadState {
    const index = id ? state.entries.findIndex((entry) => entry.id === id) : -1
    const existing = state.entries[index]
    if (existing) {
        return { ...state, entries: replaceAt(state.entries, index, build(existing.key)) }
    }
    const [key, next] = takeKey(state)
    return { ...next, entries: [...state.entries, build(key)] }
}

function applyHuman(
    state: ChatThreadState,
    content: string,
    id: string | undefined,
    traceId: string | undefined,
    at: string
): ChatThreadState {
    const text = stripInjectedContext(content)
    let index = traceId ? state.entries.findIndex((entry) => entry.kind === 'user' && entry.traceId === traceId) : -1
    if (index === -1) {
        const lastUser = lastUserIndex(state.entries)
        index = lastUser !== -1 && state.entries[lastUser]?.text === text ? lastUser : -1
    }
    const existing = state.entries[index]
    if (existing?.kind === 'user') {
        // Keep the typed text: the echo carries the full prompt, context block included.
        const echoed: UserChatEntry = { ...existing, id: id ?? existing.id, status: 'completed' }
        return { ...state, entries: replaceAt(state.entries, index, echoed) }
    }
    const [key, next] = takeKey(state)
    const user: UserChatEntry = {
        kind: 'user',
        role: 'user',
        key,
        id: id ?? key,
        traceId,
        text,
        at,
        status: 'completed',
    }
    return { ...next, entries: [...state.entries, user] }
}

function applyAssistant(state: ChatThreadState, content: string, id: string | undefined, at: string): ChatThreadState {
    const temp = isTempId(id)
    const turnStart = lastUserIndex(state.entries) + 1
    // Every turn restarts at `temp-0`, so a temp id only names a snapshot of the running turn; a UUID is global.
    let index = id ? state.entries.findIndex((entry, i) => entry.id === id && (!temp || i >= turnStart)) : -1
    if (index === -1 && !temp) {
        // The final message replaces the oldest snapshot still streaming in this turn.
        index = state.entries.findIndex(
            (entry, i) =>
                i >= turnStart && entry.kind === 'assistant' && entry.status === 'loading' && isTempId(entry.id)
        )
    }
    const status = temp ? 'loading' : 'completed'
    const existing = state.entries[index]
    if (existing) {
        const progress = existing.kind === 'assistant' ? existing.progress : undefined
        const updated: AssistantChatEntry = {
            kind: 'assistant',
            role: 'assistant',
            key: existing.key,
            id: id ?? existing.id,
            text: content,
            at: existing.at,
            status,
            ...(progress ? { progress } : {}),
        }
        return { ...state, entries: replaceAt(state.entries, index, updated) }
    }
    const [key, next] = takeKey(state)
    const created: AssistantChatEntry = {
        kind: 'assistant',
        role: 'assistant',
        key,
        id: id ?? key,
        text: content,
        at,
        status,
    }
    return { ...next, entries: [...state.entries, created] }
}

function applyMessage(state: ChatThreadState, message: ConversationMessage, at: string): ChatThreadState {
    switch (message.type) {
        case 'human':
            return applyHuman(state, message.content, message.id, message.trace_id, at)
        case 'ai':
            return applyAssistant(state, message.content, message.id, at)
        case 'ai/failure':
            return appendFailure(state, message.content?.trim() || GENERIC_FAILURE, at, message.id)
        case 'ai/artifact': {
            const { content } = message
            const text =
                content.content_type === 'notebook'
                    ? content.title
                        ? `Notebook: ${content.title}`
                        : 'PostHog AI wrote a notebook.'
                    : content.name
                      ? `Chart: ${content.name}`
                      : 'PostHog AI made a chart.'
            const id = message.id ?? `artifact-${message.artifact_id}`
            return upsertById(
                state,
                id,
                (key): LinkChatEntry => ({
                    kind: 'link',
                    role: 'assistant',
                    key,
                    id,
                    text,
                    at,
                    status: 'completed',
                    target:
                        message.source === 'insight' && message.artifact_id
                            ? { kind: 'insight', shortId: message.artifact_id }
                            : { kind: 'conversation' },
                })
            )
        }
        case 'tool':
            // Tool results only drive web UI through `ui_payload`; the app has none of those tools.
            return state
    }
}

function applyEvent(state: ChatThreadState, event: ConversationEvent, at: string): ChatThreadState {
    switch (event.type) {
        case 'conversation':
            return { ...state, title: event.conversation.title ?? state.title }
        case 'message':
            return applyMessage(state, event.message, at)
        case 'update': {
            const { id, content } = event.update
            if (!content) {
                return state
            }
            const index = state.entries.findIndex((entry) => entry.id === id)
            const existing = state.entries[index]
            if (existing?.kind === 'assistant') {
                return { ...state, entries: replaceAt(state.entries, index, { ...existing, progress: content }) }
            }
            if (existing) {
                return state
            }
            // The update can arrive before the message that made the tool call.
            const [key, next] = takeKey(state)
            const placeholder: AssistantChatEntry = {
                kind: 'assistant',
                role: 'assistant',
                key,
                id,
                text: '',
                at,
                status: 'loading',
                progress: content,
            }
            return { ...next, entries: [...state.entries, placeholder] }
        }
        case 'generation_error':
            return appendFailure(state, GENERIC_FAILURE, at)
        case 'approval': {
            const id = `approval-${event.approval.proposal_id}`
            return upsertById(
                { ...state, entries: settle(state.entries) },
                id,
                (key): LinkChatEntry => ({
                    kind: 'link',
                    role: 'assistant',
                    key,
                    id,
                    text: APPROVAL_TEXT,
                    at,
                    status: 'completed',
                    target: { kind: 'conversation' },
                })
            )
        }
    }
}

export function chatThreadReducer(state: ChatThreadState, action: ChatThreadAction): ChatThreadState {
    switch (action.type) {
        case 'sent': {
            const [key, next] = takeKey(state)
            const user: UserChatEntry = {
                kind: 'user',
                role: 'user',
                key,
                id: key,
                traceId: action.traceId,
                text: action.text,
                at: action.at,
                status: 'completed',
            }
            return { ...next, replayPending: false, entries: [...settle(state.entries), user] }
        }
        case 'event': {
            if (!state.replayPending) {
                return applyEvent(state, action.event, action.at)
            }
            const cut = {
                ...state,
                replayPending: false,
                entries: state.entries.slice(0, lastUserIndex(state.entries) + 1),
            }
            return applyEvent(cut, action.event, action.at)
        }
        case 'resuming':
            return { ...state, replayPending: true }
        case 'retrying': {
            const index = lastUserIndex(state.entries)
            const user = state.entries[index]
            if (user?.kind !== 'user') {
                return state
            }
            const entries = [...state.entries.slice(0, index), { ...user, traceId: action.traceId }]
            return { ...state, replayPending: false, entries }
        }
        case 'withdrawn': {
            // The server was still busy with the previous turn, so this message waits until that turn ends.
            const index = lastUserIndex(state.entries)
            if (index === -1 || index !== state.entries.length - 1) {
                return state
            }
            return { ...state, entries: state.entries.slice(0, index) }
        }
        case 'finished': {
            const entries = settle(state.entries)
            const last = entries[entries.length - 1]
            if (last?.kind === 'user') {
                return appendFailure({ ...state, replayPending: false, entries }, EMPTY_REPLY_FAILURE, action.at)
            }
            return { ...state, replayPending: false, entries }
        }
        case 'stopped':
            return { ...state, replayPending: false, entries: settle(state.entries) }
        case 'failed':
            return appendFailure({ ...state, replayPending: false }, action.message, action.at)
        case 'hydrated': {
            const base: ChatThreadState = {
                ...state,
                entries: [],
                replayPending: false,
                title: action.title ?? state.title,
            }
            const rebuilt = action.messages.reduce((acc, message) => applyMessage(acc, message, action.at), base)
            return { ...rebuilt, entries: settle(rebuilt.entries) }
        }
        case 'reset':
            return { ...initialChatThread, nextKey: state.nextKey }
    }
}
