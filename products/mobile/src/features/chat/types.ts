import type { ChatMessage } from '@/model/types'

export type ChatEntryStatus = 'loading' | 'completed' | 'error'

interface ChatEntryBase extends ChatMessage {
    /** Stable React key. `id` changes when a streamed snapshot becomes the final message; `key` does not. */
    key: string
    status: ChatEntryStatus
}

export interface UserChatEntry extends ChatEntryBase {
    kind: 'user'
    role: 'user'
    /** Trace id of the request that sent it, so the server's echo replaces this bubble. */
    traceId?: string
}

export interface AssistantChatEntry extends ChatEntryBase {
    kind: 'assistant'
    role: 'assistant'
    progress?: string
}

export interface FailureChatEntry extends ChatEntryBase {
    kind: 'failure'
    role: 'assistant'
    status: 'error'
}

export type ChatLinkTarget = { kind: 'conversation' } | { kind: 'insight'; shortId: string }

export interface LinkChatEntry extends ChatEntryBase {
    kind: 'link'
    role: 'assistant'
    target: ChatLinkTarget
}

export type ChatEntry = UserChatEntry | AssistantChatEntry | FailureChatEntry | LinkChatEntry

export interface ChatReportContext {
    reportId: string
    title: string
    webUrl?: string
    status?: string
    priority?: string
    pullRequestUrl?: string
    summary?: string
    canAct: boolean
}

export interface ChatInboxContextItem {
    title: string
    webUrl?: string
    sourceLabel: string
    state: string
    needsInput: boolean
}

export type ChatContext =
    | { kind: 'reports'; reports: ChatReportContext[] }
    | { kind: 'inbox'; items: ChatInboxContextItem[] }
    | { kind: 'none' }

export interface ChatError {
    kind: 'credits' | 'throttled' | 'busy' | 'unavailable' | 'not_found' | 'invalid' | 'auth' | 'network' | 'unknown'
    message: string
    retryAfterSeconds?: number
}
