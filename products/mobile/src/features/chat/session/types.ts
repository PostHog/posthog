import type { DecisionAnswerInput, DecisionQuestion, PullRequestView, TaskRunStatus } from '@/model/types'

import type { PendingAttachment } from '../attachments/types'
import type { ChatRunOptions } from '../chatRunOptions'
import type { ChatContext, ChatError } from '../types'
import type { SessionRunConfig } from './sessionRun'

// A session is a sandbox task run shown in the chat sheet. The web equivalent is the `TaskRunChat`
// surface in `products/posthog_ai/frontend`; its folded thread shapes are `types/streamTypes.ts` there.

export type SessionToolStatus = 'pending' | 'in_progress' | 'completed' | 'failed'

export interface SessionToolInvocation {
    toolCallId: string
    /** The agent's own tool (`Bash`, `Edit`) or the inner PostHog MCP tool, else the raw ACP tool name. */
    toolName: string
    /** The ACP `title`, already shortened for a phone row. */
    title?: string
    /** The PostHog MCP `context` sentence: why the agent made this call. */
    detail?: string
    /** The ACP `kind` (`execute`, `read`, `edit`, …), which the activity summary counts. */
    kind?: string
    status: SessionToolStatus
    errorMessage?: string
}

export interface SessionProgressStep {
    key: string
    label: string
    status: SessionToolStatus
    detail?: string
}

/** A file a message carried. The ids come from the echo's sandbox path; an optimistic send has only the name. */
export interface SessionAttachment {
    artifactId?: string
    runId?: string
    name: string
    isImage: boolean
    /** The picked file on this device, so the bubble can draw a thumbnail. History has none. */
    localUri?: string
}

export interface SessionUserItem {
    kind: 'user'
    id: string
    text: string
    attachments?: SessionAttachment[]
}

export interface SessionAssistantItem {
    kind: 'assistant'
    id: string
    text: string
    complete: boolean
}

export interface SessionThoughtItem {
    kind: 'thought'
    id: string
    text: string
    complete: boolean
}

export interface SessionToolItem {
    kind: 'tool'
    id: string
    /** Look the call up in `Session.invocations`. */
    toolCallId: string
}

/** The agent finished a turn and waits. Draws as spacing, never as text. */
export interface SessionTurnEndItem {
    kind: 'turn_end'
    id: string
}

export interface SessionErrorItem {
    kind: 'error'
    id: string
    message: string
    /** `crash` is the friendlier agent-crash copy; `undelivered` means a message did not reach the agent. */
    variant: 'error' | 'crash' | 'undelivered'
}

/** One line of run news: a task milestone, a compaction, a cleared conversation, a status spinner. */
export interface SessionNoticeItem {
    kind: 'notice'
    id: string
    text: string
    tone: 'completed' | 'failed' | 'info'
    /** Still running (compacting, clearing), so the row shows a spinner. */
    spinning?: boolean
}

export interface SessionProgressItem {
    kind: 'progress'
    id: string
    steps: SessionProgressStep[]
}

export type SessionThreadItem =
    | SessionUserItem
    | SessionAssistantItem
    | SessionThoughtItem
    | SessionToolItem
    | SessionTurnEndItem
    | SessionErrorItem
    | SessionNoticeItem
    | SessionProgressItem

/** Consecutive thoughts and tool calls fold into one row, as the web thread does. */
export interface SessionActivityGroup {
    kind: 'activity'
    id: string
    items: (SessionThoughtItem | SessionToolItem)[]
}

export type SessionDisplayItem = Exclude<SessionThreadItem, SessionThoughtItem | SessionToolItem> | SessionActivityGroup

/** `working` while the agent generates; `idle` once it waits for a reply or the run ended. */
export type SessionPhase = 'idle' | 'working' | 'reconnecting'

export interface SessionHistory {
    /** `idle` once the stored run log has loaded. */
    status: 'loading' | 'idle' | 'error'
    error: ChatError | null
}

export type SessionDecisionKind = 'question' | 'plan' | 'permission'

export interface SessionDecision {
    question: DecisionQuestion
    kind: SessionDecisionKind
    /** The tool call the agent waits on. The thread must not draw it as running while the person decides. */
    toolCallId: string
}

/** How a message reaches the agent. */
export interface SendOptions {
    /**
     * Joins the live turn instead of waiting for it to end (`params.steer` on `user_message`).
     * Honored only while `canSteer`; otherwise the message goes as an ordinary follow-up.
     */
    steer?: boolean
    /** How many staged messages this text carries, for analytics. 0 for a message typed and sent directly. */
    queuedCount?: number
    /** Files that upload before the message goes; see docs/CHAT.md. */
    attachments?: readonly PendingAttachment[]
}

export interface Session {
    /** Null for a new chat until `start` creates its task. */
    taskId: string | null
    /** The run the sheet follows. Null until the task loads. */
    runId: string | null
    title: string | null
    runStatus: TaskRunStatus | null
    items: SessionThreadItem[]
    invocations: ReadonlyMap<string, SessionToolInvocation>
    phase: SessionPhase
    /** What the agent does right now: the progress label, else the latest tool title, else the server stage. */
    stage?: string
    history: SessionHistory
    /** A question, plan approval or permission the agent waits on. Replaces the composer while set. */
    decision?: SessionDecision
    pullRequest?: PullRequestView
    pullRequests?: PullRequestView[]
    /** The run's own failure, from `error_message` or an `_posthog/error` frame. */
    runError?: string
    /** A send or an answer is in flight. */
    isSending: boolean
    isStopping: boolean
    /** One transient line above the composer, such as an answer that did not reach the agent. */
    notice?: string
    unsentText?: string
    runConfig?: SessionRunConfig
    start: (text: string, context: ChatContext, options: ChatRunOptions, sendOptions?: SendOptions) => Promise<boolean>
    /**
     * Sends to the live run after it applies the changed options, or starts a run that continues this task when the
     * run has ended. Without a task it starts one, as `start` does.
     */
    send: (text: string, context: ChatContext, options?: ChatRunOptions, sendOptions?: SendOptions) => Promise<boolean>
    /**
     * The live turn can take a steered message now: the run works, the stream showed the agent generating, no decision
     * waits, and no send or stop is in flight.
     */
    canSteer: boolean
    answer: (input: DecisionAnswerInput) => Promise<void>
    /** Asks the agent to stop the current turn. Only while `phase` is not `idle`. */
    stop: () => void
    reloadHistory: () => Promise<void>
    reset: () => void
    dismissNotice: () => void
}
