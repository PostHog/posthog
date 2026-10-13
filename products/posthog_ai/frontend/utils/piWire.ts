import { ReasoningEffortEnumApi, type TaskRunCommandRequestApi } from 'products/tasks/frontend/generated/api.schemas'

import type { PermissionRequestRecord } from '../types/streamTypes'
import type { PermissionOption, StoredLogEntry } from '../types/wireTypes'

export const PI_EXTENSION_UI_META_KEY = 'piExtensionUi'
export const PI_EXTENSION_CONFIRM_OPTION_ID = 'confirm'
export const PI_EXTENSION_CANCEL_OPTION_ID = 'cancel'
const PI_MCP_ALLOW_ONCE_OPTION_ID = 'allow'
const PI_MCP_REJECT_HINT = 'Blocks this tool call. The agent keeps working.'

const PI_WIRE_TYPES = new Set([
    'pi_event',
    'pi_run_started',
    'pi_extension_event',
    'extension_ui_request',
    'extension_ui_response',
    'extension_error',
])

export interface PiExtensionUiMeta {
    id: string
    method: string
}

export type PiExtensionUiResponse =
    | { type: 'extension_ui_response'; id: string; value: string }
    | { type: 'extension_ui_response'; id: string; confirmed: boolean }
    | { type: 'extension_ui_response'; id: string; cancelled: true }

export interface PiMcpPermissionResponse {
    id: string
    type: 'mcp_permission_response'
    requestId: string
    decision: string
}

export type PiPermissionCommand = PiExtensionUiResponse | PiMcpPermissionResponse

/** The model and thinking level a live Pi session reports through `get_state`. */
export interface PiSessionConfig {
    model: string | null
    effort: string | null
}

export const PI_GET_STATE_COMMAND = { type: 'get_state' } as const

export function piSetModelCommand(modelId: string): { type: 'set_model'; provider: 'posthog'; modelId: string } {
    return { type: 'set_model', provider: 'posthog', modelId }
}

export function piSetThinkingLevelCommand(level: string): { type: 'set_thinking_level'; level: string } {
    return { type: 'set_thinking_level', level }
}

// Pi's thinking levels and the catalogue's reasoning efforts share these names. Pi also has levels
// the catalogue does not describe (`off`, `minimal`), which read as no effort rather than a fake one.
const PI_THINKING_LEVELS_AS_EFFORTS = new Set<string>([
    ReasoningEffortEnumApi.Low,
    ReasoningEffortEnumApi.Medium,
    ReasoningEffortEnumApi.High,
    ReasoningEffortEnumApi.Xhigh,
    ReasoningEffortEnumApi.Max,
])

export function parsePiSessionConfig(result: unknown): PiSessionConfig | null {
    const data = isRecord(result) ? result.data : undefined
    if (!isRecord(data)) {
        return null
    }
    const modelId = isRecord(data.model) ? optionalString(data.model.id) : undefined
    const thinkingLevel = optionalString(data.thinkingLevel)
    const effort = thinkingLevel && PI_THINKING_LEVELS_AS_EFFORTS.has(thinkingLevel) ? thinkingLevel : null
    return modelId || effort ? { model: modelId ?? null, effort } : null
}

type Notification = StoredLogEntry['notification']

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function optionalString(value: unknown): string | undefined {
    return typeof value === 'string' && value ? value : undefined
}

export function isPiWireEntry(value: unknown): value is Record<string, unknown> {
    return isRecord(value) && typeof value.type === 'string' && PI_WIRE_TYPES.has(value.type)
}

/**
 * A Pi tool call already carries the renderer contract in `_meta.posthog` (the agent-facing tool name,
 * the MCP descriptor, the proxied MCP call), so the record maps onto the ACP update field by field. A
 * title equal to the raw tool name says nothing a renderer does not know, so it is left out.
 */
function toolCallUpdate(sessionUpdate: 'tool_call' | 'tool_call_update', toolCall: unknown): Notification | null {
    if (!isRecord(toolCall) || typeof toolCall.id !== 'string' || !toolCall.id) {
        return null
    }
    const update: Record<string, unknown> = { sessionUpdate, toolCallId: toolCall.id }
    for (const field of ['kind', 'status', 'content', 'locations', 'rawInput', 'rawOutput', '_meta'] as const) {
        if (toolCall[field] !== undefined && toolCall[field] !== null) {
            update[field] = toolCall[field]
        }
    }
    const title = optionalString(toolCall.title)
    if (title && title !== toolCall.name) {
        update.title = title
    }
    return { method: 'session/update', params: { update } }
}

function conversationEventNotification(event: unknown): Notification | null {
    if (!isRecord(event)) {
        return null
    }
    switch (event.type) {
        case 'user_message':
            return { method: '_posthog/user_message', params: { content: event.content } }
        case 'assistant_message_chunk':
            return {
                method: 'session/update',
                params: { update: { sessionUpdate: 'agent_message_chunk', content: event.content } },
            }
        case 'assistant_thought_chunk':
            return {
                method: 'session/update',
                params: { update: { sessionUpdate: 'agent_thought_chunk', content: event.content } },
            }
        case 'tool_call_started':
            return toolCallUpdate('tool_call', event.toolCall)
        case 'tool_call_updated':
            return toolCallUpdate('tool_call_update', event.toolCall)
        case 'progress':
            return {
                method: '_posthog/progress',
                params: {
                    step: event.step,
                    status: event.status,
                    label: event.label,
                    group: event.group,
                    ...(event.detail !== undefined ? { detail: event.detail } : {}),
                },
            }
        case 'runtime_status':
            return {
                method: '_posthog/status',
                params: {
                    status: event.status,
                    isComplete: event.isComplete === true,
                    ...(event.error !== undefined ? { error: event.error } : {}),
                },
            }
        case 'runtime_error':
            return { method: '_posthog/error', params: { message: event.message, errorType: event.errorType } }
        case 'turn_completed':
            return {
                method: '_posthog/turn_complete',
                params: {
                    stopReason: event.stopReason === 'aborted' ? 'cancelled' : event.stopReason,
                    ...(isRecord(event.usage) ? { usage: event.usage } : {}),
                },
            }
        case 'queue_update':
            return {
                method: '_posthog/pi_queue_update',
                params: { steering: event.steering, followUp: event.followUp },
            }
        default:
            return null
    }
}

function extensionQuestionRequest(message: Record<string, unknown>, id: string, method: string): Notification {
    const title = optionalString(message.title) ?? 'The agent needs your input'
    const choices = method === 'select' && Array.isArray(message.options) ? message.options.filter(optionalString) : []
    const options: PermissionOption[] = choices.length
        ? choices.map((label, index) => ({ optionId: `option_${index}`, name: label, kind: 'allow_once' }))
        : [{ optionId: 'option_0', name: 'Submit', kind: 'allow_once' }]
    return {
        method: '_posthog/permission_request',
        params: {
            requestId: id,
            toolCall: {
                toolCallId: `pi-extension-${id}`,
                title,
                kind: 'question',
                _meta: {
                    codeToolKind: 'question',
                    questions: [
                        {
                            question: title,
                            multiSelect: false,
                            options: choices.map((label) => ({ label })),
                            ...(optionalString(message.placeholder) ? { placeholder: message.placeholder } : {}),
                            ...(typeof message.prefill === 'string' ? { defaultAnswer: message.prefill } : {}),
                            ...(method === 'editor' ? { multiline: true } : {}),
                        },
                    ],
                    [PI_EXTENSION_UI_META_KEY]: { id, method },
                },
            },
            options,
        },
    }
}

function extensionConfirmRequest(message: Record<string, unknown>, id: string): Notification {
    const title = optionalString(message.title) ?? 'The agent needs your confirmation'
    const detail = optionalString(message.message)
    return {
        method: '_posthog/permission_request',
        params: {
            requestId: id,
            toolCall: {
                toolCallId: `pi-extension-${id}`,
                kind: 'other',
                description: detail ? `${title}\n\n${detail}` : title,
                _meta: { [PI_EXTENSION_UI_META_KEY]: { id, method: 'confirm' } },
            },
            options: [
                { optionId: PI_EXTENSION_CONFIRM_OPTION_ID, name: 'Confirm', kind: 'allow_once' },
                {
                    optionId: PI_EXTENSION_CANCEL_OPTION_ID,
                    name: 'Cancel',
                    kind: 'reject_once',
                    _meta: { hint: 'Declines this request. The agent keeps working.' },
                },
            ],
        },
    }
}

function extensionNotice(message: string): Notification {
    return { method: '_posthog/status', params: { status: 'extension_notice', isComplete: true, message } }
}

function extensionNotification(message: unknown): Notification | null {
    if (!isRecord(message)) {
        return null
    }
    if (message.type === 'extension_ui_response') {
        const id = optionalString(message.id)
        return id ? { method: '_posthog/permission_resolved', params: { requestId: id } } : null
    }
    if (message.type === 'extension_error') {
        const error = optionalString(message.error)
        if (!error) {
            return null
        }
        const extension = optionalString(message.extensionPath)?.split(/[\\/]/).pop()
        const during = optionalString(message.event)
        return extensionNotice(extension ? `${extension} failed${during ? ` during ${during}` : ''}: ${error}` : error)
    }
    if (message.type !== 'extension_ui_request') {
        return null
    }
    const id = optionalString(message.id)
    const method = optionalString(message.method)
    if (!id || !method) {
        return null
    }
    switch (method) {
        case 'select':
        case 'input':
        case 'editor':
            return extensionQuestionRequest(message, id, method)
        case 'confirm':
            return extensionConfirmRequest(message, id)
        case 'notify': {
            const text = optionalString(message.message)
            const level = optionalString(message.notifyType) ?? 'info'
            if (!text) {
                return null
            }
            return level === 'warning' || level === 'error'
                ? extensionNotice(text)
                : { method: '_posthog/console', params: { message: text, level } }
        }
        default:
            return { method: '_posthog/pi_extension_event', params: message }
    }
}

function piNotification(value: Record<string, unknown>): Notification | null {
    switch (value.type) {
        case 'pi_event':
            return conversationEventNotification(value.event)
        case 'pi_run_started':
            return {
                method: '_posthog/run_started',
                params: {
                    ...(typeof value.runId === 'string' ? { runId: value.runId } : {}),
                    ...(typeof value.taskId === 'string' ? { taskId: value.taskId } : {}),
                },
            }
        case 'pi_extension_event':
            return extensionNotification(isRecord(value.notification) ? value.notification.params : undefined)
        default:
            return extensionNotification(value)
    }
}

export function translatePiWireEntry(value: unknown): StoredLogEntry | null {
    if (!isPiWireEntry(value)) {
        return null
    }
    const notification = piNotification(value)
    if (!notification) {
        return null
    }
    const coveredEventIds = Array.isArray(value.covered_event_ids)
        ? value.covered_event_ids.filter((id): id is string => typeof id === 'string' && id !== '')
        : []
    return {
        type: 'notification',
        ...(typeof value.timestamp === 'string' ? { timestamp: value.timestamp } : {}),
        ...(typeof value.event_id === 'string' && value.event_id ? { event_id: value.event_id } : {}),
        ...(typeof value.source_run_id === 'string' ? { source_run_id: value.source_run_id } : {}),
        ...(coveredEventIds.length > 0 ? { covered_event_ids: coveredEventIds } : {}),
        notification,
    }
}

export function withPiMcpOptions(record: PermissionRequestRecord): PermissionRequestRecord {
    if (readPiExtensionUiMeta(record.rawToolCall.meta)) {
        return record
    }
    const options = record.options.map((option) =>
        option.kind.startsWith('reject') ? { ...option, hint: PI_MCP_REJECT_HINT } : option
    )
    const needsOneShotAllow =
        options.some((option) => option.optionId === 'allow_always') &&
        !options.some((option) => option.kind === 'allow_once')
    return {
        ...record,
        options: needsOneShotAllow
            ? [{ optionId: PI_MCP_ALLOW_ONCE_OPTION_ID, name: 'Allow', kind: 'allow_once' }, ...options]
            : options,
    }
}

export function readPiExtensionUiMeta(meta: unknown): PiExtensionUiMeta | null {
    const value = isRecord(meta) ? meta[PI_EXTENSION_UI_META_KEY] : undefined
    if (!isRecord(value) || typeof value.id !== 'string' || typeof value.method !== 'string') {
        return null
    }
    return { id: value.id, method: value.method }
}

export function piRpcRequest(
    command: Record<string, unknown> & { type: string },
    id: string
): TaskRunCommandRequestApi {
    return { jsonrpc: '2.0', method: 'pi/rpc', id, params: { command: { ...command, id } } }
}

export function piRpcResponseError(result: unknown): string | null {
    if (!isRecord(result) || result.success !== false) {
        return null
    }
    return optionalString(result.error) ?? 'The agent rejected the command'
}

export function buildPiPermissionCommand(
    request: { requestId: string; meta: unknown; options: PermissionOption[] },
    response: { optionId: string; customInput?: string; answers?: Record<string, string> },
    commandId: string
): PiPermissionCommand {
    const extension = readPiExtensionUiMeta(request.meta)
    if (!extension) {
        return {
            id: commandId,
            type: 'mcp_permission_response',
            requestId: request.requestId,
            decision: response.optionId,
        }
    }
    if (response.optionId === PI_EXTENSION_CANCEL_OPTION_ID) {
        return { type: 'extension_ui_response', id: extension.id, cancelled: true }
    }
    if (extension.method === 'confirm') {
        return {
            type: 'extension_ui_response',
            id: extension.id,
            confirmed: response.optionId === PI_EXTENSION_CONFIRM_OPTION_ID,
        }
    }
    const answer = Object.values(response.answers ?? {})[0]
    const chosen = request.options.find((option) => option.optionId === response.optionId)
    return {
        type: 'extension_ui_response',
        id: extension.id,
        value: answer ?? response.customInput ?? (extension.method === 'select' ? chosen?.name : undefined) ?? '',
    }
}
