import type { DecisionAnswer, TaskRunStatus, TaskRunView } from '@/model/types'

import type { ToolCallSource } from './toolTitle'

export interface PermissionOption {
    optionId: string
    name: string
    /** `allow_once`, `allow_always`, `reject_once`, or a legacy `reject*` kind. Match by prefix. */
    kind: string
    customInput: boolean
}

export interface AgentQuestionOption {
    label: string
    description?: string
}

export interface AgentQuestion {
    question: string
    header?: string
    multiSelect: boolean
    options: AgentQuestionOption[]
}

export interface PermissionToolCall {
    toolCallId: string
    rawServerName: string
    rawToolName: string
    input: Record<string, unknown>
    title?: string
    kind?: string
    meta?: unknown
}

export interface PermissionRecord {
    requestDetails?: string
    requestId: string
    toolCallId: string
    toolName: string
    options: PermissionOption[]
    title?: string
    rawToolCall: PermissionToolCall
    questions?: AgentQuestion[]
}

export type PendingRequestKind = 'question' | 'plan' | 'permission'

export interface PendingRequest {
    record: PermissionRecord
    kind: PendingRequestKind
    replayed: boolean
}

export interface RunStreamState {
    taskId: string
    runId: string
    status: TaskRunStatus
    phase?: TaskRunView['phase']
    connection?: TaskRunView['connection']
    serverStage?: string
    toolTitle?: string
    latestToolCallId?: string
    /** The latest call's source, so a bare update can still be described by what the call runs. */
    latestToolCall?: ToolCallSource
    progressLabel?: string
    messageOpen: boolean
    prUrl?: string
    prUrls: string[]
    errorMessage?: string
    mode?: string
    pending?: PendingRequest
    handledRequestIds: string[]
    turnEnded: boolean
    activity: number
    liveActivitySeen?: boolean
}

export type AnswerDelivery = 'sending' | 'delivered'

export interface HandoffAnswer extends DecisionAnswer {
    canUndo: boolean
}

export interface RunTarget {
    taskId: string
    runId?: string
}

export interface LiveTaskRunView extends TaskRunView {
    errorMessage?: string
}

export function runErrorMessage(task: TaskRunView | undefined): string | undefined {
    const message = (task as LiveTaskRunView | undefined)?.errorMessage
    return typeof message === 'string' && message.trim() ? message.trim() : undefined
}
