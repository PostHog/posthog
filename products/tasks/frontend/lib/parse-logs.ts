export type LogEntryType = 'console' | 'agent' | 'tool' | 'user' | 'raw' | 'system'
export type LogLevel = 'info' | 'warn' | 'error' | 'debug'
export type ToolStatus = 'pending' | 'running' | 'completed' | 'error'

export interface LogEntry {
    id: string
    type: LogEntryType
    timestamp?: string
    level?: LogLevel
    message?: string
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

function parseACPNotification(parsed: ACPNotification, id: string, toolMap: Map<string, LogEntry>): LogEntry | null {
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
                if (update.content?.type === 'text' && update.content.text) {
                    return {
                        id,
                        type: 'agent',
                        timestamp,
                        message: update.content.text,
                    }
                }
                return null

            case 'tool_call': {
                const toolCallId = update.toolCallId || id
                const entry: LogEntry = {
                    id,
                    type: 'tool',
                    timestamp,
                    toolName: update._meta?.claudeCode?.toolName || update.title || 'Unknown Tool',
                    toolCallId,
                    toolStatus: normalizeToolStatus(update.status),
                    toolArgs: update.rawInput,
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
                        if (update._meta?.claudeCode?.toolResponse !== undefined) {
                            existing.toolResult = update._meta.claudeCode.toolResponse
                        } else if (update.rawOutput !== undefined) {
                            existing.toolResult = update.rawOutput
                        }
                        return null
                    }
                }
                return null
            }

            default:
                return null
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

        if (parsed.toolName || parsed.tool_name || parsed.tool) {
            return {
                id,
                type: 'tool',
                timestamp: parsed.timestamp || parsed.time,
                toolName: parsed.toolName || parsed.tool_name || parsed.tool,
                toolStatus: 'completed',
                toolArgs: parsed.args || parsed.arguments || parsed.input,
                toolResult: parsed.result || parsed.output,
            }
        }

        if (parsed.level || parsed.severity) {
            return {
                id,
                type: 'console',
                timestamp: parsed.timestamp || parsed.time,
                level: normalizeLevel(parsed.level || parsed.severity),
                message: parsed.message || parsed.msg || parsed.text || JSON.stringify(parsed),
            }
        }

        if (parsed.role === 'user' || parsed.type === 'user') {
            return {
                id,
                type: 'user',
                timestamp: parsed.timestamp || parsed.time,
                message: parsed.content || parsed.message || parsed.text,
            }
        }

        if (parsed.role === 'assistant' || parsed.type === 'agent' || parsed.type === 'assistant') {
            return {
                id,
                type: 'agent',
                timestamp: parsed.timestamp || parsed.time,
                message: parsed.content || parsed.message || parsed.text,
            }
        }

        if (parsed.message || parsed.msg || parsed.text) {
            return {
                id,
                type: 'console',
                timestamp: parsed.timestamp || parsed.time,
                level: 'info',
                message: parsed.message || parsed.msg || parsed.text,
            }
        }

        return {
            id,
            type: 'raw',
            raw: line,
        }
    } catch {
        return {
            id,
            type: 'raw',
            raw: line,
        }
    }
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
            if (entry.type === 'agent' && lastEntry?.type === 'agent') {
                lastEntry.message = (lastEntry.message || '') + (entry.message || '')
            } else {
                entries.push(entry)
            }
        }
    }

    return entries
}
