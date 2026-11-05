import type { SseEvent } from '@/api/sse'
import { asRecord, isRecord } from '@/lib/records'

import type { SessionThreadItem } from '../session/types'

export interface ClassicMessage {
    id: string
    data: Record<string, unknown>
    complete: boolean
}

export interface ClassicApproval {
    id: string
    preview: string
    toolName: string
}

export interface ClassicForm {
    id: string
    questions: Record<string, unknown>[]
}

export interface ClassicState {
    messages: ClassicMessage[]
    nextMessageId: number
    title: string | null
    progress: string | null
    approval: ClassicApproval | null
    form: ClassicForm | null
    error: string | null
}

export const EMPTY_CLASSIC_STATE: ClassicState = {
    messages: [],
    nextMessageId: 0,
    title: null,
    progress: null,
    approval: null,
    form: null,
    error: null,
}

function approvalFrom(value: unknown): ClassicApproval | null {
    const data = asRecord(value) ?? {}
    return typeof data.proposal_id === 'string' && data.decision_status === 'pending'
        ? {
              id: data.proposal_id,
              preview: typeof data.preview === 'string' ? data.preview : 'Allow this change?',
              toolName: typeof data.tool_name === 'string' ? data.tool_name : 'PostHog AI',
          }
        : null
}

function pendingForm(messages: ClassicMessage[]): ClassicForm | null {
    const data = messages.at(-1)?.data
    if (data?.type !== 'ai' || !Array.isArray(data.tool_calls)) return null
    const call = data.tool_calls.find((call) => isRecord(call) && call.name === 'create_form')
    const args = asRecord(call?.args)
    if (typeof call?.id !== 'string' || !Array.isArray(args?.questions)) return null
    const questions = args.questions.filter(isRecord)
    return questions.length ? { id: call.id, questions } : null
}

export function appendClassicMessage(state: ClassicState, data: Record<string, unknown>): ClassicState {
    if (typeof data.type !== 'string') {
        return state
    }
    const wireId = typeof data.id === 'string' ? data.id : null
    const complete = wireId !== null && !wireId.startsWith('temp-')
    let index = wireId ? state.messages.findIndex((message) => message.data.id === wireId) : -1
    if (index < 0 && data.type === 'human') {
        index = state.messages.findLastIndex(
            (message) =>
                message.data.type === 'human' &&
                !message.complete &&
                (data.trace_id ? message.data.trace_id === data.trace_id : message.data.content === data.content)
        )
    }
    const finalCalls = Array.isArray(data.tool_calls) ? data.tool_calls.filter(isRecord) : []
    const pendingIndex = state.messages.findIndex((message) => {
        if (message.complete || message.data.type !== data.type) return false
        const calls = Array.isArray(message.data.tool_calls) ? message.data.tool_calls.filter(isRecord) : []
        if (calls.length) return calls.some((call) => finalCalls.some((finalCall) => finalCall.id === call.id))
        return (
            typeof message.data.content === 'string' &&
            message.data.content.length > 0 &&
            typeof data.content === 'string' &&
            data.content.startsWith(message.data.content)
        )
    })
    if (index < 0 && data.type !== 'human' && (!wireId || complete)) {
        index =
            pendingIndex >= 0
                ? pendingIndex
                : state.messages.findIndex((message) => !message.complete && message.data.type === data.type)
    }
    const entry: ClassicMessage = {
        id: complete && wireId ? wireId : `stream-${state.nextMessageId}`,
        data,
        complete,
    }
    const messages = [...state.messages]
    if (index >= 0) {
        messages[index] = { ...entry, id: messages[index]?.id ?? entry.id }
    } else {
        messages.push(entry)
    }
    if (complete && index >= 0 && pendingIndex >= 0 && pendingIndex !== index) {
        messages.splice(pendingIndex, 1)
    }
    return {
        ...state,
        messages,
        form: pendingForm(messages),
        nextMessageId: state.nextMessageId + (index < 0 ? 1 : 0),
        progress: data.type === 'ai' ? null : state.progress,
        error:
            data.type === 'ai/failure'
                ? String(data.content || 'PostHog AI ran into a problem. Try again.')
                : state.error,
    }
}

export function classicHistory(
    messages: readonly Record<string, unknown>[],
    title: string | null,
    approvals: readonly Record<string, unknown>[] = []
): ClassicState {
    const entries = messages.map((data, index) => ({
        id: typeof data.id === 'string' ? data.id : `history-${index}`,
        data,
        complete: true,
    }))
    return {
        ...EMPTY_CLASSIC_STATE,
        title,
        messages: entries,
        nextMessageId: entries.length,
        form: pendingForm(entries),
        approval: approvals.map(approvalFrom).find((approval) => approval !== null) ?? null,
    }
}

export function reduceClassicEvent(state: ClassicState, event: SseEvent): ClassicState {
    let data: unknown
    try {
        data = JSON.parse(event.data)
    } catch {
        return state
    }
    if (!isRecord(data)) {
        return state
    }
    switch (event.event) {
        case 'message':
            return appendClassicMessage(state, data)
        case 'conversation':
            return { ...state, title: typeof data.title === 'string' ? data.title : state.title }
        case 'update':
            return {
                ...state,
                progress: typeof data.content === 'string' ? data.content : state.progress,
            }
        case 'approval':
            return { ...state, approval: approvalFrom(data) }
        case 'status':
            return data.type === 'generation_error'
                ? { ...state, error: 'PostHog AI ran into a problem. Try again.' }
                : state
        default:
            return state
    }
}

function visualizationLink(data: Record<string, unknown>, projectUrl: string): string | null {
    const content = asRecord(data.content) ?? {}
    const shortId = data.short_id ?? (data.source === 'insight' ? data.artifact_id : content.short_id)
    if (typeof shortId === 'string') {
        return `[View insight](${projectUrl}/insights/${encodeURIComponent(shortId)})`
    }
    const query = data.answer ?? content.query
    if (!isRecord(query)) return null
    const insightKinds = [
        'TrendsQuery',
        'FunnelsQuery',
        'RetentionQuery',
        'PathsQuery',
        'StickinessQuery',
        'LifecycleQuery',
    ]
    const visualization =
        query.kind === 'HogQLQuery'
            ? { kind: 'DataVisualizationNode', source: query }
            : insightKinds.includes(String(query.kind))
              ? { kind: 'InsightVizNode', source: query, showHeader: true }
              : query
    return `[View chart](${projectUrl}/insights/new#q=${encodeURIComponent(JSON.stringify(visualization))})`
}

function notebookText(data: Record<string, unknown>, projectUrl: string): string {
    const content = asRecord(data.content) ?? {}
    const blocks = Array.isArray(content.blocks) ? content.blocks : []
    const parts = blocks.map((value): string => {
        const block = asRecord(value) ?? {}
        if (block.type === 'markdown' && typeof block.content === 'string') return block.content
        if (block.type === 'visualization')
            return visualizationLink({ content: block }, projectUrl) ?? 'Chart unavailable.'
        if (block.type === 'error' && typeof block.message === 'string') return block.message
        return 'Open this report on the web to view this content.'
    })
    if (content.is_saved === true && typeof data.artifact_id === 'string') {
        parts.push(`[View notebook](${projectUrl}/notebooks/${encodeURIComponent(data.artifact_id)})`)
    }
    return parts.filter(Boolean).join('\n\n') || 'This report has no content yet.'
}

export function classicThreadItems(state: ClassicState, projectUrl: string): SessionThreadItem[] {
    return state.messages.flatMap((message): SessionThreadItem[] => {
        const data = message.data
        const text = typeof data.content === 'string' ? data.content : ''
        switch (data.type) {
            case 'human':
                return [{ kind: 'user', id: message.id, text }]
            case 'ai':
                return text ? [{ kind: 'assistant', id: message.id, text, complete: message.complete, projectUrl }] : []
            case 'ai/reasoning':
                return text ? [{ kind: 'thought', id: message.id, text, complete: message.complete }] : []
            case 'ai/viz':
            case 'ai/artifact': {
                const link =
                    asRecord(data.content)?.content_type === 'notebook'
                        ? notebookText(data, projectUrl)
                        : visualizationLink(data, projectUrl)
                return link ? [{ kind: 'assistant', id: message.id, text: link, complete: true, projectUrl }] : []
            }
            case 'ai/multi_viz':
                return Array.isArray(data.visualizations)
                    ? data.visualizations.flatMap((viz, index): SessionThreadItem[] => {
                          const link = visualizationLink(asRecord(viz) ?? {}, projectUrl)
                          return link
                              ? [{ kind: 'assistant', id: `${message.id}-${index}`, text: link, complete: true }]
                              : []
                      })
                    : []
            default:
                return []
        }
    })
}
