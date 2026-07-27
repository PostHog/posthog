export type LogEntryType = 'console' | 'agent' | 'tool' | 'user' | 'raw' | 'system' | 'thinking'
export type LogLevel = 'info' | 'warn' | 'error' | 'debug'
export type ToolStatus = 'pending' | 'running' | 'completed' | 'error'

export interface LogEntryAttachment {
    id: string
    label: string
}

export interface LogEntry {
    id: string
    type: LogEntryType
    timestamp?: string
    level?: LogLevel
    message?: string
    attachments?: LogEntryAttachment[]
    toolName?: string
    toolCallId?: string
    toolStatus?: ToolStatus
    toolArgs?: Record<string, unknown>
    toolResult?: unknown
    raw?: string
}

function normalizeLevel(level?: string): LogLevel {
    if (!level) {
        return 'info'
    }
    const lower = level.toLowerCase()
    if (lower === 'warning') {
        return 'warn'
    }
    if (['info', 'warn', 'error', 'debug'].includes(lower)) {
        return lower as LogLevel
    }
    return 'info'
}

/**
 * ACP serializes arrays/strings in rawOutput as index-keyed objects:
 *   "hello" → {"0":"h","1":"e","2":"l","3":"l","4":"o"}
 *   [{type:"text"}] → {"0":{type:"text"}}
 * Detect and reconstruct the original value.
 */
function normalizeRawOutput(value: unknown): unknown {
    if (typeof value !== 'object' || value === null || Array.isArray(value)) {
        return value
    }
    const obj = value as Record<string, unknown>
    if (!('0' in obj)) {
        return value
    }
    // Reconstruct array from sequential numeric keys
    const arr: unknown[] = []
    for (let i = 0; String(i) in obj; i++) {
        arr.push(obj[String(i)])
    }
    if (arr.length === 0) {
        return value
    }
    // If every element is a single character, it was a string
    if (arr.every((v) => typeof v === 'string' && v.length === 1)) {
        return arr.join('')
    }
    return arr
}

function normalizeToolStatus(status?: string | null): ToolStatus {
    switch (status) {
        case 'pending':
            return 'pending'
        case 'in_progress':
            return 'running'
        case 'completed':
            return 'completed'
        case 'failed':
            return 'error'
        default:
            return 'pending'
    }
}

interface ACPNotification {
    type: 'notification'
    timestamp: string
    notification: {
        jsonrpc: string
        method?: string
        id?: number
        params?: Record<string, unknown>
        result?: Record<string, unknown>
    }
}

interface SessionPromptParams {
    prompt?: PromptBlock[]
}

interface PromptTextBlock {
    type: 'text'
    text?: string
}

interface PromptResourceLinkBlock {
    type: 'resource_link'
    uri?: string
    name?: string
}

type PromptBlock = PromptTextBlock | PromptResourceLinkBlock | { type: string; [key: string]: unknown }

interface SessionUpdateParams {
    sessionId?: string
    update?: {
        sessionUpdate?: string
        content?: { type: string; text?: string }
        toolCallId?: string
        title?: string
        status?: string
        rawInput?: Record<string, unknown>
        rawOutput?: unknown
        _meta?: { claudeCode?: { toolName?: string; toolResponse?: unknown } }
    }
}

function isACPNotification(parsed: unknown): parsed is ACPNotification {
    return (
        typeof parsed === 'object' &&
        parsed !== null &&
        'type' in parsed &&
        (parsed as ACPNotification).type === 'notification' &&
        'notification' in parsed
    )
}

function getAttachmentLabel(block: PromptResourceLinkBlock): string | null {
    if (block.name?.trim()) {
        return block.name.trim()
    }

    if (!block.uri) {
        return null
    }

    try {
        const pathname = new URL(block.uri).pathname
        const segments = pathname.split('/').filter(Boolean)
        return segments.at(-1) ?? block.uri
    } catch {
        const segments = block.uri.split('/').filter(Boolean)
        return segments.at(-1) ?? block.uri
    }
}

function isPromptTextBlock(block: PromptBlock): block is PromptTextBlock {
    return block.type === 'text'
}

function isPromptResourceLinkBlock(block: PromptBlock): block is PromptResourceLinkBlock {
    return block.type === 'resource_link'
}

function parsePromptBlocks(prompt: PromptBlock[], id: string): Pick<LogEntry, 'message' | 'attachments'> | null {
    const textParts: string[] = []
    const attachments: LogEntryAttachment[] = []

    prompt.forEach((block, index) => {
        if (isPromptTextBlock(block) && block.text) {
            textParts.push(block.text)
        }

        if (isPromptResourceLinkBlock(block)) {
            const label = getAttachmentLabel(block)
            if (label) {
                attachments.push({
                    id: `${id}-attachment-${index}`,
                    label,
                })
            }
        }
    })

    if (textParts.length === 0 && attachments.length === 0) {
        return null
    }

    return {
        message: textParts.join(''),
        attachments: attachments.length > 0 ? attachments : undefined,
    }
}

function parseACPNotification(
    parsed: ACPNotification,
    id: string,
    toolMap: Map<string, LogEntry>,
    onToolEntryUpdated?: (entry: LogEntry) => void
): LogEntry | null {
    const { notification, timestamp } = parsed
    const method = notification.method

    if (method === '_posthog/console') {
        const params = notification.params as { level?: string; message?: string } | undefined
        return {
            id,
            type: 'console',
            timestamp,
            level: normalizeLevel(params?.level),
            message: params?.message || '',
        }
    }

    if (method === 'session/update') {
        const params = notification.params as SessionUpdateParams | undefined
        const update = params?.update
        if (!update?.sessionUpdate) {
            return null
        }

        switch (update.sessionUpdate) {
            case 'user_message_chunk':
                if (update.content?.type === 'text' && update.content.text) {
                    return {
                        id,
                        type: 'user',
                        timestamp,
                        message: update.content.text,
                    }
                }
                return null

            case 'agent_message_chunk':
            case 'agent_message':
                if (update.content?.type === 'text' && update.content.text) {
                    return {
                        id,
                        type: 'agent',
                        timestamp,
                        message: update.content.text,
                    }
                }
                return null

            case 'agent_thought_chunk':
                if (update.content?.type === 'text' && update.content.text) {
                    return {
                        id,
                        type: 'thinking',
                        timestamp,
                        message: update.content.text,
                    }
                }
                return null

            case 'tool_call': {
                const toolCallId = update.toolCallId || id
                const existing = toolMap.get(toolCallId)
                if (existing) {
                    // Update existing entry in place (ACP sends tool_call for both start and completion)
                    existing.toolStatus = normalizeToolStatus(update.status)
                    if (update.rawInput && !existing.toolArgs) {
                        existing.toolArgs = update.rawInput
                    }
                    if (update._meta?.claudeCode?.toolResponse !== undefined) {
                        existing.toolResult = update._meta.claudeCode.toolResponse
                    } else if (update.rawOutput !== undefined) {
                        existing.toolResult = normalizeRawOutput(update.rawOutput)
                    }
                    onToolEntryUpdated?.({ ...existing })
                    return null
                }
                const entry: LogEntry = {
                    id,
                    type: 'tool',
                    timestamp,
                    toolName: update._meta?.claudeCode?.toolName || update.title || 'Unknown Tool',
                    toolCallId,
                    toolStatus: normalizeToolStatus(update.status),
                    toolArgs: update.rawInput && Object.keys(update.rawInput).length > 0 ? update.rawInput : undefined,
                }
                toolMap.set(toolCallId, entry)
                return entry
            }

            case 'tool_call_update': {
                const toolCallId = update.toolCallId
                if (toolCallId) {
                    const existing = toolMap.get(toolCallId)
                    if (existing) {
                        existing.toolStatus = normalizeToolStatus(update.status)
                        if (update.rawInput && Object.keys(update.rawInput).length > 0) {
                            existing.toolArgs = update.rawInput
                        }
                        if (update._meta?.claudeCode?.toolResponse !== undefined) {
                            existing.toolResult = update._meta.claudeCode.toolResponse
                        } else if (update.rawOutput !== undefined) {
                            existing.toolResult = normalizeRawOutput(update.rawOutput)
                        }
                        onToolEntryUpdated?.({ ...existing })
                        return null
                    }
                }
                return null
            }

            default:
                return null
        }
    }

    if (method === 'session/prompt') {
        const params = notification.params as SessionPromptParams | undefined
        if (!params?.prompt) {
            return null
        }

        const parsedPrompt = parsePromptBlocks(params.prompt, id)
        if (!parsedPrompt) {
            return null
        }

        return {
            id,
            type: 'user',
            timestamp,
            message: parsedPrompt.message,
            attachments: parsedPrompt.attachments,
        }
    }

    if (notification.result && notification.id !== undefined) {
        return null
    }

    if (notification.id !== undefined && method) {
        return null
    }

    if (method?.startsWith('__posthog/') || method?.startsWith('_posthog/')) {
        return null
    }

    return null
}

function parseLogObject(parsed: Record<string, unknown>, id: string): LogEntry | null {
    if (parsed.toolName || parsed.tool_name || parsed.tool) {
        return {
            id,
            type: 'tool',
            timestamp: (parsed.timestamp || parsed.time) as string | undefined,
            toolName: (parsed.toolName || parsed.tool_name || parsed.tool) as string,
            toolStatus: 'completed',
            toolArgs: (parsed.args || parsed.arguments || parsed.input) as Record<string, unknown> | undefined,
            toolResult: parsed.result || parsed.output,
        }
    }

    if (parsed.level || parsed.severity) {
        return {
            id,
            type: 'console',
            timestamp: (parsed.timestamp || parsed.time) as string | undefined,
            level: normalizeLevel((parsed.level || parsed.severity) as string | undefined),
            message: ((parsed.message || parsed.msg || parsed.text) as string) || JSON.stringify(parsed),
        }
    }

    if (parsed.role === 'user' || parsed.type === 'user') {
        return {
            id,
            type: 'user',
            timestamp: (parsed.timestamp || parsed.time) as string | undefined,
            message: (parsed.content || parsed.message || parsed.text) as string | undefined,
        }
    }

    if (parsed.role === 'assistant' || parsed.type === 'agent' || parsed.type === 'assistant') {
        return {
            id,
            type: 'agent',
            timestamp: (parsed.timestamp || parsed.time) as string | undefined,
            message: (parsed.content || parsed.message || parsed.text) as string | undefined,
        }
    }

    if (parsed.message || parsed.msg || parsed.text) {
        return {
            id,
            type: 'console',
            timestamp: (parsed.timestamp || parsed.time) as string | undefined,
            level: 'info',
            message: (parsed.message || parsed.msg || parsed.text) as string,
        }
    }

    return null
}

function parseLogLine(line: string, index: number, toolMap: Map<string, LogEntry>): LogEntry | null {
    const id = `log-${index}`
    const trimmed = line.trim()

    if (!trimmed.startsWith('{') && !trimmed.startsWith('[')) {
        return {
            id,
            type: 'raw',
            raw: line,
        }
    }

    try {
        const parsed = JSON.parse(line)

        if (isACPNotification(parsed)) {
            return parseACPNotification(parsed, id, toolMap)
        }

        return parseLogObject(parsed, id) ?? { id, type: 'raw', raw: line }
    } catch {
        return {
            id,
            type: 'raw',
            raw: line,
        }
    }
}

/**
 * Parse a single ACP event object from an SSE stream into a LogEntry.
 * Uses the same logic as parseLogs but for individual events arriving in real-time.
 */
export function parseLogEvent(
    event: Record<string, unknown>,
    id: string,
    toolMap: Map<string, LogEntry>,
    onToolEntryUpdated?: (entry: LogEntry) => void
): LogEntry | null {
    if (isACPNotification(event)) {
        return parseACPNotification(event as ACPNotification, id, toolMap, onToolEntryUpdated)
    }

    return parseLogObject(event, id)
}

export function parseLogs(logs: string): LogEntry[] {
    if (!logs) {
        return []
    }

    const toolMap = new Map<string, LogEntry>()
    const entries: LogEntry[] = []

    const lines = logs.split('\n').filter((line) => line.trim())

    for (let i = 0; i < lines.length; i++) {
        const entry = parseLogLine(lines[i], i, toolMap)
        if (entry !== null) {
            const lastEntry = entries[entries.length - 1]
            if (
                (entry.type === 'agent' && lastEntry?.type === 'agent') ||
                (entry.type === 'thinking' && lastEntry?.type === 'thinking')
            ) {
                lastEntry.message = (lastEntry.message || '') + (entry.message || '')
            } else {
                entries.push(entry)
            }
        }
    }

    return entries
}
