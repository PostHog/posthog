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

export interface ClassicState {
    messages: ClassicMessage[]
    title: string | null
    progress: string | null
    approval: ClassicApproval | null
    error: string | null
}

export const EMPTY_CLASSIC_STATE: ClassicState = {
    messages: [],
    title: null,
    progress: null,
    approval: null,
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
    if (index < 0 && data.type !== 'human') {
        index = state.messages.findLastIndex((message) => !message.complete && message.data.type === data.type)
    }
    const entry: ClassicMessage = { id: wireId ?? `stream-${state.messages.length}`, data, complete }
    const messages = [...state.messages]
    if (index >= 0) {
        messages[index] = { ...entry, id: messages[index]?.id ?? entry.id }
    } else {
        messages.push(entry)
    }
    return {
        ...state,
        messages,
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
    return {
        ...EMPTY_CLASSIC_STATE,
        title,
        messages: messages.map((data, index) => ({
            id: typeof data.id === 'string' ? data.id : `history-${index}`,
            data,
            complete: true,
        })),
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
            return { ...state, progress: typeof data.content === 'string' ? data.content : state.progress }
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
    return isRecord(query)
        ? `[View chart](${projectUrl}/insights/new#q=${encodeURIComponent(JSON.stringify({ kind: 'InsightVizNode', source: query }))})`
        : null
}

export function classicThreadItems(state: ClassicState, projectUrl: string): SessionThreadItem[] {
    return state.messages.flatMap((message): SessionThreadItem[] => {
        const data = message.data
        const text = typeof data.content === 'string' ? data.content : ''
        switch (data.type) {
            case 'human':
                return [{ kind: 'user', id: message.id, text }]
            case 'ai':
                return text ? [{ kind: 'assistant', id: message.id, text, complete: message.complete }] : []
            case 'ai/reasoning':
                return text ? [{ kind: 'thought', id: message.id, text, complete: message.complete }] : []
            case 'ai/viz':
            case 'ai/artifact': {
                const link = visualizationLink(data, projectUrl)
                return link ? [{ kind: 'assistant', id: message.id, text: link, complete: true }] : []
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
