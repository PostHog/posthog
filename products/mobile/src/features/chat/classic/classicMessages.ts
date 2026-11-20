import type { SseEvent } from '@/api/sse'
import { asRecord, isRecord } from '@/lib/records'
import { classicVisualizationItems } from '../classicVisualizations'
import type { SessionThreadItem } from '../session/types'
import { classicIntermediateIds, classicThinkingItems, classicToolCalls } from './classicActivity'

export interface ClassicMessage {
    id: string
    data: Record<string, unknown>
    complete: boolean
}

export interface ClassicApproval {
    id: string
    preview: string
    toolName: string
    toolCallId?: string
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
    toolUpdates: Record<string, string>
}

export const EMPTY_CLASSIC_STATE: ClassicState = {
    messages: [],
    nextMessageId: 0,
    title: null,
    progress: null,
    approval: null,
    form: null,
    error: null,
    toolUpdates: {},
}

interface ClassicProjection {
    projectUrl: string
    traceId?: string
    complete: boolean
    thinkingComplete: boolean
    intermediate: boolean
    items: SessionThreadItem[]
}

const projections = new WeakMap<ClassicMessage, ClassicProjection>()

function approvalFrom(value: unknown): ClassicApproval | null {
    const data = asRecord(value) ?? {}
    return typeof data.proposal_id === 'string' && data.decision_status === 'pending'
        ? {
              id: data.proposal_id,
              preview: typeof data.preview === 'string' ? data.preview : 'Allow this change?',
              toolName: typeof data.tool_name === 'string' ? data.tool_name : 'PostHog AI',
              ...(typeof data.original_tool_call_id === 'string' ? { toolCallId: data.original_tool_call_id } : {}),
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
    const complete =
        (wireId !== null && !wireId.startsWith('temp-')) ||
        (data.type === 'tool' && typeof data.tool_call_id === 'string')
    let index = wireId ? state.messages.findIndex((message) => message.data.id === wireId) : -1
    if (index < 0 && data.type === 'tool' && typeof data.tool_call_id === 'string') {
        index = state.messages.findIndex(
            (message) => message.data.type === 'tool' && message.data.tool_call_id === data.tool_call_id
        )
    }
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
            if (typeof data.tool_call_id === 'string' && typeof data.content === 'string') {
                if (state.toolUpdates?.[data.tool_call_id] === data.content) return state
                return {
                    ...state,
                    toolUpdates: {
                        ...state.toolUpdates,
                        [data.tool_call_id]: data.content,
                    },
                }
            }
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

export function classicThreadItems(state: ClassicState, projectUrl: string, working = false): SessionThreadItem[] {
    let currentTraceId: string | undefined
    const intermediateIds = classicIntermediateIds(state.messages)
    const lastHuman = state.messages.findLastIndex((message) => message.data.type === 'human')
    return state.messages.flatMap((message, index): SessionThreadItem[] => {
        const data = message.data
        const text = typeof data.content === 'string' ? data.content : ''
        const traceId = typeof data.trace_id === 'string' && data.trace_id ? data.trace_id : undefined
        if (data.type === 'human') currentTraceId = traceId
        const feedback = traceId || currentTraceId ? { traceId: traceId ?? currentTraceId } : {}
        const calls = data.type === 'ai' ? classicToolCalls(data) : []
        const complete = !working || index < lastHuman || message.complete
        const thinkingComplete =
            !working || index < state.messages.length - 1 || (data.type === 'ai' && (!!text || calls.length > 0))
        const intermediate = intermediateIds.has(message.id)
        const cached = projections.get(message)
        if (
            cached &&
            cached.projectUrl === projectUrl &&
            cached.traceId === feedback.traceId &&
            cached.complete === complete &&
            cached.thinkingComplete === thinkingComplete &&
            cached.intermediate === intermediate
        ) {
            return cached.items
        }
        const items = ((): SessionThreadItem[] => {
            switch (data.type) {
                case 'human':
                    return [{ kind: 'user', id: message.id, text }]
                case 'ai': {
                    const thoughts = classicThinkingItems(message, thinkingComplete, projectUrl)
                    const content: SessionThreadItem[] = text
                        ? intermediate
                            ? [
                                  {
                                      kind: 'thought',
                                      id: message.id,
                                      text,
                                      complete,
                                      ...(projectUrl ? { projectUrl } : {}),
                                  },
                              ]
                            : [
                                  {
                                      kind: 'assistant',
                                      id: message.id,
                                      text,
                                      complete,
                                      projectUrl,
                                      ...feedback,
                                  },
                              ]
                        : []
                    return [
                        ...thoughts,
                        ...content,
                        ...calls.map(
                            (call): SessionThreadItem => ({
                                kind: 'tool',
                                id: `${message.id}-tool-${call.id}`,
                                toolCallId: String(call.id),
                            })
                        ),
                    ]
                }
                case 'ai/reasoning':
                    return text
                        ? [
                              {
                                  kind: 'thought',
                                  id: message.id,
                                  text,
                                  complete: thinkingComplete,
                                  ...(projectUrl ? { projectUrl } : {}),
                              },
                          ]
                        : []
                case 'ai/failure':
                    return [
                        {
                            kind: 'error',
                            id: message.id,
                            message: text || 'PostHog AI ran into a problem. Try again.',
                            variant: 'error',
                        },
                    ]
                case 'ai/viz':
                case 'ai/artifact':
                case 'ai/multi_viz':
                    return classicVisualizationItems(data, message.id, projectUrl, feedback)
                default:
                    return []
            }
        })()
        projections.set(message, {
            projectUrl,
            traceId: feedback.traceId,
            complete,
            thinkingComplete,
            intermediate,
            items,
        })
        return items
    })
}
