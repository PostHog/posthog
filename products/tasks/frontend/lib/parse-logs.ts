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

function isACPNotification(parsed: unknown): parsed is ACPNotification {
    return (
        typeof parsed === 'object' &&
        parsed !== null &&
        'type' in parsed &&
        (parsed as ACPNotification).type === 'notification' &&
        'notification' in parsed
    )
}

function parseACPNotification(parsed: ACPNotification, id: string): LogEntry | null {
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

    if (method === 'session/new' || method === 'initialize') {
        return {
            id,
            type: 'system',
            timestamp,
            message: method === 'initialize' ? 'Initializing agent...' : 'Starting session...',
        }
    }

    if (notification.result && notification.id !== undefined) {
        return null
    }

    return null
}

export function parseLogLine(line: string, index: number): LogEntry | null {
    const id = `log-${index}`

    try {
        const parsed = JSON.parse(line)

        if (isACPNotification(parsed)) {
            return parseACPNotification(parsed, id)
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

        return null
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

    return logs
        .split('\n')
        .filter((line) => line.trim())
        .map((line, index) => parseLogLine(line, index))
        .filter((entry): entry is LogEntry => entry !== null)
}
