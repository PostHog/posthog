import type { TaskRunCommandRequestApi } from 'products/tasks/frontend/generated/api.schemas'

import type { PermissionOption, PermissionRequestFrame, StoredLogEntry } from '../types/wireTypes'

export const PI_EXTENSION_UI_META_KEY = 'piExtensionUi'
export const PI_EXTENSION_CONFIRM_OPTION_ID = 'confirm'
export const PI_EXTENSION_CANCEL_OPTION_ID = 'cancel'
const PI_MCP_ALLOW_ONCE_OPTION_ID = 'allow'
const PI_MCP_REJECT_HINT = 'Blocks this tool call. The agent keeps working.'

const PI_BUILTIN_TOOL_NAMES: Record<string, string> = {
    read: 'Read',
    bash: 'Bash',
    edit: 'Edit',
    write: 'Write',
    grep: 'Grep',
    find: 'Glob',
    ls: 'LS',
}

const PI_FILE_PATH_TOOLS = new Set(['read', 'edit', 'write'])

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

function mcpToolParts(name: string): { server: string; tool: string } | undefined {
    if (!name.startsWith('mcp_') && !name.includes('__') && !name.endsWith('_exec')) {
        return undefined
    }
    const bare = name.replace(/^mcp_+/, '')
    const separator = bare.indexOf('__')
    if (separator > 0) {
        return { server: bare.slice(0, separator), tool: bare.slice(separator + 2) }
    }
    if (bare.endsWith('_exec') && bare.length > '_exec'.length) {
        return { server: bare.slice(0, -'_exec'.length), tool: 'exec' }
    }
    return undefined
}

function piToolMeta(name: string | undefined, meta: unknown): Record<string, unknown> | undefined {
    const existing = isRecord(meta) ? meta : undefined
    if (!name || (existing && isRecord(existing.posthog))) {
        return existing
    }
    const builtin = PI_BUILTIN_TOOL_NAMES[name]
    const mcp = builtin ? undefined : mcpToolParts(name)
    const posthog = mcp ? { toolName: `mcp__${mcp.server}__${mcp.tool}`, mcp } : { toolName: builtin ?? name }
    return { ...existing, posthog }
}

function mcpToolLabel(value: string): string {
    const label = value.replace(/[_-]+/g, ' ').trim()
    return label.charAt(0).toUpperCase() + label.slice(1)
}

// Pi calls every non-PostHog MCP tool through one proxy tool named `mcp`, so its title is always
// `mcp`. The started frame names the real tool in `details`, and the completed frame names it in
// `_meta.posthog`. This title matches the one PostHog Desktop shows.
function piMcpProxyTitle(details: unknown, meta: unknown): string | undefined {
    const posthog = isRecord(meta) && isRecord(meta.posthog) ? meta.posthog : undefined
    const proxy = isRecord(details) && typeof details.kind === 'string' ? details : posthog?.mcpProxy
    if (!isRecord(proxy)) {
        return undefined
    }
    if (proxy.kind === 'search') {
        return 'Search MCP tools'
    }
    const descriptor = isRecord(posthog?.mcp) ? posthog.mcp : undefined
    if (typeof descriptor?.server === 'string' && typeof descriptor.tool === 'string') {
        const title = optionalString(descriptor.title)
        return `${descriptor.server} - ${title ?? mcpToolLabel(descriptor.tool)}`
    }
    const name = optionalString(proxy.name)?.replace(/^mcp_+/, '')
    if (proxy.kind !== 'tool' || !name) {
        return undefined
    }
    const [server, ...tool] = name.split(name.includes('__') ? '__' : '_')
    return server && tool.length > 0 ? `${server} - ${mcpToolLabel(tool.join('_'))}` : mcpToolLabel(name)
}

function piToolInput(name: string | undefined, rawInput: unknown): unknown {
    if (!name || !PI_FILE_PATH_TOOLS.has(name) || !isRecord(rawInput) || typeof rawInput.path !== 'string') {
        return rawInput
    }
    return rawInput.file_path === undefined ? { ...rawInput, file_path: rawInput.path } : rawInput
}

function toolCallUpdate(sessionUpdate: 'tool_call' | 'tool_call_update', toolCall: unknown): Notification | null {
    if (!isRecord(toolCall) || typeof toolCall.id !== 'string' || !toolCall.id) {
        return null
    }
    const name = optionalString(toolCall.name)
    const update: Record<string, unknown> = { sessionUpdate, toolCallId: toolCall.id }
    for (const field of ['title', 'kind', 'status', 'content', 'locations', 'rawOutput'] as const) {
        if (toolCall[field] !== undefined && toolCall[field] !== null) {
            update[field] = toolCall[field]
        }
    }
    if (name && PI_BUILTIN_TOOL_NAMES[name] && update.title === name) {
        delete update.title
    }
    const mcpProxyTitle = name === 'mcp' || !name ? piMcpProxyTitle(toolCall.details, toolCall._meta) : undefined
    if (mcpProxyTitle) {
        update.title = mcpProxyTitle
    }
    if (toolCall.rawInput !== undefined) {
        update.rawInput = piToolInput(name, toolCall.rawInput)
    }
    const meta = piToolMeta(name, toolCall._meta)
    if (meta) {
        update._meta = meta
    }
    return { method: 'session/update', params: { update } }
}

// The Pi agent server writes each non-image attachment to `<artifactId>-<name>` and lists the paths
// under this heading at the end of the prompt text.
const PI_ATTACHED_FILES_PATTERN = /(?:\n\n)?Attached files:\n((?:- [^\n]+\n?)+)$/
const PI_ATTACHMENT_FILE_PATTERN = /^([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})-(.+)$/i

function piAttachedFiles(text: string): { text: string; files: Record<string, unknown>[] } {
    const match = PI_ATTACHED_FILES_PATTERN.exec(text)
    if (!match) {
        return { text, files: [] }
    }
    const files = match[1]
        .split('\n')
        .map((line) => line.replace(/^- /, '').trim())
        .filter(Boolean)
        .map((path) => {
            const fileName = path.split('/').pop() ?? path
            const named = PI_ATTACHMENT_FILE_PATTERN.exec(fileName)
            return {
                type: 'resource_link',
                uri: path,
                name: named ? named[2] : fileName,
                ...(named ? { artifactId: named[1] } : {}),
            }
        })
    return { text: text.slice(0, match.index), files }
}

/** Pi's echoed prompt, with its attachments as the attachment blocks the thread renders. */
function piUserContent(content: unknown): unknown {
    if (!Array.isArray(content)) {
        return content
    }
    return content.flatMap((block): unknown[] => {
        if (!isRecord(block)) {
            return [block]
        }
        if (block.type === 'text' && typeof block.text === 'string') {
            const { text, files } = piAttachedFiles(block.text)
            return [...(text ? [{ ...block, text }] : []), ...files]
        }
        if (block.type === 'image') {
            const name = optionalString(block.fileName)
            return [
                { type: 'image', ...(name ? { name } : {}), ...(block.mimeType ? { mimeType: block.mimeType } : {}) },
            ]
        }
        return [block]
    })
}

function conversationEventNotification(event: unknown): Notification | null {
    if (!isRecord(event)) {
        return null
    }
    switch (event.type) {
        case 'user_message':
            return { method: '_posthog/user_message', params: { content: piUserContent(event.content) } }
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

export function withPiMcpOptions(frame: PermissionRequestFrame): PermissionRequestFrame {
    const options = (Array.isArray(frame.options) ? frame.options : []).map((option) =>
        option.kind.startsWith('reject') ? { ...option, _meta: { ...option._meta, hint: PI_MCP_REJECT_HINT } } : option
    )
    const needsOneShotAllow =
        options.some((option) => option.optionId === 'allow_always') &&
        !options.some((option) => option.kind === 'allow_once')
    return {
        ...frame,
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

/** A `pi/rpc` relay request. The relay requires the request id to match the Pi command id. */
export function piRpcRequest(
    command: Record<string, unknown> & { type: string },
    id: string
): TaskRunCommandRequestApi {
    return { jsonrpc: '2.0', method: 'pi/rpc', id, params: { command: { ...command, id } } }
}

/** A Pi RPC response reports failure in its body, so a relay 200 can still carry a failed command. */
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
