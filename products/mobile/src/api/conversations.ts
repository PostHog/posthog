import { isRecord } from '@/lib/records'

import { apiJson, apiStream, projectPath } from './client'
import { readSse, type SseEvent } from './sse'

// Uses the LangGraph runtime (`ee/api/conversation.py`) because the sandbox runtime's endpoints declare no OAuth
// scopes, so an app token gets 403 there. The stream is not in the OpenAPI schema, so these types mirror
// `posthog/schema.py` by hand.

export type ConversationStatus = 'idle' | 'in_progress' | 'canceling'

export interface ConversationMeta {
    id: string
    status: ConversationStatus
    title: string | null
}

export interface HumanWireMessage {
    type: 'human'
    content: string
    id?: string
    trace_id?: string
}

export interface AssistantWireMessage {
    type: 'ai'
    content: string
    /** `temp-N` while the text streams as full snapshots, then a UUID for the final message. */
    id?: string
    tool_calls?: { id: string; name: string }[]
}

export interface ToolWireMessage {
    type: 'tool'
    content: string
    tool_call_id: string
    id?: string
    ui_payload?: Record<string, unknown>
}

export interface FailureWireMessage {
    type: 'ai/failure'
    content?: string
    id?: string
}

export interface ArtifactWireMessage {
    type: 'ai/artifact'
    id?: string
    /** An insight short id when `source` is `insight`. */
    artifact_id: string
    source: 'artifact' | 'insight' | 'state'
    content: {
        content_type: 'visualization' | 'notebook'
        name?: string
        title?: string
    }
}

export type ConversationMessage =
    | HumanWireMessage
    | AssistantWireMessage
    | ToolWireMessage
    | FailureWireMessage
    | ArtifactWireMessage

export interface ConversationUpdate {
    id: string
    tool_call_id: string
    /** Progress text. Null for a subagent update, which carries a tool call object instead. */
    content: string | null
}

export interface ConversationApproval {
    proposal_id: string
    tool_name?: string
}

export type ConversationEvent =
    | { type: 'conversation'; conversation: ConversationMeta }
    | { type: 'message'; message: ConversationMessage }
    | { type: 'update'; update: ConversationUpdate }
    | { type: 'generation_error' }
    | { type: 'approval'; approval: ConversationApproval }

export interface ConversationRequest {
    /** Client-generated UUID. The server creates the conversation on the first message. */
    conversationId: string
    /** New UUID per request. The server echoes it on the human message. */
    traceId: string
    /** The prompt, or null to reattach to a turn that is still running. */
    content: string | null
}

function optionalString(value: unknown): string | undefined {
    return typeof value === 'string' ? value : undefined
}

function parseJson(data: string): unknown {
    try {
        return JSON.parse(data) as unknown
    } catch {
        return undefined
    }
}

function parseMeta(value: unknown): ConversationMeta | null {
    if (!isRecord(value) || typeof value.id !== 'string') {
        return null
    }
    const status = value.status === 'in_progress' || value.status === 'canceling' ? value.status : 'idle'
    return { id: value.id, status, title: optionalString(value.title) ?? null }
}

export function parseConversationMessage(value: unknown): ConversationMessage | null {
    if (!isRecord(value)) {
        return null
    }
    const id = optionalString(value.id)
    switch (value.type) {
        case 'human':
            return typeof value.content === 'string'
                ? { type: 'human', content: value.content, id, trace_id: optionalString(value.trace_id) }
                : null
        case 'ai': {
            const toolCalls = Array.isArray(value.tool_calls)
                ? value.tool_calls
                      .filter(isRecord)
                      .map((call) => ({ id: optionalString(call.id) ?? '', name: optionalString(call.name) ?? '' }))
                : undefined
            return { type: 'ai', content: optionalString(value.content) ?? '', id, tool_calls: toolCalls }
        }
        case 'tool':
            return {
                type: 'tool',
                content: optionalString(value.content) ?? '',
                tool_call_id: optionalString(value.tool_call_id) ?? '',
                id,
                ui_payload: isRecord(value.ui_payload) ? value.ui_payload : undefined,
            }
        case 'ai/failure':
            return { type: 'ai/failure', content: optionalString(value.content), id }
        case 'ai/artifact': {
            const content = isRecord(value.content) ? value.content : {}
            const source = value.source === 'insight' || value.source === 'state' ? value.source : 'artifact'
            return {
                type: 'ai/artifact',
                id,
                artifact_id: optionalString(value.artifact_id) ?? '',
                source,
                content: {
                    content_type: content.content_type === 'notebook' ? 'notebook' : 'visualization',
                    name: optionalString(content.name),
                    title: optionalString(content.title),
                },
            }
        }
        default:
            return null
    }
}

export function parseConversationEvent(event: SseEvent): ConversationEvent | null {
    const data = parseJson(event.data)
    switch (event.event) {
        case 'conversation': {
            const conversation = parseMeta(data)
            return conversation ? { type: 'conversation', conversation } : null
        }
        case 'message': {
            const message = parseConversationMessage(data)
            return message ? { type: 'message', message } : null
        }
        case 'update':
            if (!isRecord(data) || typeof data.id !== 'string') {
                return null
            }
            return {
                type: 'update',
                update: {
                    id: data.id,
                    tool_call_id: optionalString(data.tool_call_id) ?? '',
                    content: optionalString(data.content) ?? null,
                },
            }
        case 'status':
            return isRecord(data) && data.type === 'generation_error' ? { type: 'generation_error' } : null
        case 'approval':
            if (!isRecord(data) || typeof data.proposal_id !== 'string') {
                return null
            }
            return {
                type: 'approval',
                approval: { proposal_id: data.proposal_id, tool_name: optionalString(data.tool_name) },
            }
        default:
            return null
    }
}

export async function openConversationStream(request: ConversationRequest, signal: AbortSignal): Promise<Response> {
    return apiStream(projectPath('conversations/'), {
        method: 'POST',
        json: { conversation: request.conversationId, trace_id: request.traceId, content: request.content },
        signal,
    })
}

// The server closes the body to end a turn; there is no terminal event. Callers check `signal.aborted` afterwards,
// because an abort can also end the read without an error.
export async function readConversationStream(
    response: Response,
    onEvent: (event: ConversationEvent) => void,
    signal: AbortSignal
): Promise<void> {
    await readSse(
        response,
        (frame) => {
            const event = parseConversationEvent(frame)
            if (event) {
                onEvent(event)
            }
        },
        signal
    )
}

export interface ConversationDetail extends ConversationMeta {
    messages: ConversationMessage[]
}

/** The server returns 404 until the conversation has a title, so a brand-new conversation cannot be loaded this way. */
export async function fetchConversation(conversationId: string, signal?: AbortSignal): Promise<ConversationDetail> {
    const body = await apiJson<unknown>(projectPath(`conversations/${conversationId}/`), { signal })
    const meta = parseMeta(body)
    if (!meta || !isRecord(body)) {
        throw new Error('The conversation response was not readable')
    }
    const messages = Array.isArray(body.messages)
        ? body.messages
              .map(parseConversationMessage)
              .filter((message): message is ConversationMessage => message !== null)
        : []
    return { ...meta, messages }
}
