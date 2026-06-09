import type { AcpMessage, JsonRpcMessage } from './acp-types'

/**
 * Parse newline-delimited S3 session-log text into raw `AcpMessage` events
 * suitable for `buildConversationItems`.
 *
 * The stored log format (see `StoredLogEntry` in acp-types) wraps each
 * JSON-RPC message in `{ type, timestamp, notification: { method, id, params,
 * result, error } }`. Some lines store the bare JSON-RPC message instead. This
 * unwraps both shapes into the `{ type: "acp_message", ts, message }` envelope
 * the pipeline expects.
 *
 * It preserves the index-keyed-object `rawOutput` normalization quirk from the
 * legacy `lib/parse-logs.ts` parser: ACP serializes arrays/strings inside tool
 * `rawOutput` as index-keyed objects, which we reconstruct here so downstream
 * tool renderers see the original value.
 */

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

/** Apply `normalizeRawOutput` in place to a session/update tool payload. */
function normalizeSessionUpdateRawOutput(message: JsonRpcMessage): void {
    if (!('method' in message) || message.method !== 'session/update') {
        return
    }
    const params = message.params as { update?: { sessionUpdate?: string; rawOutput?: unknown } } | undefined
    const update = params?.update
    if (!update) {
        return
    }
    if (
        (update.sessionUpdate === 'tool_call' || update.sessionUpdate === 'tool_call_update') &&
        update.rawOutput !== undefined
    ) {
        update.rawOutput = normalizeRawOutput(update.rawOutput)
    }
}

interface RawStoredLine {
    type?: string
    timestamp?: string
    ts?: number
    notification?: {
        jsonrpc?: string
        id?: number
        method?: string
        params?: unknown
        result?: unknown
        error?: unknown
    }
    // Bare JSON-RPC fields (some lines store the message inline)
    jsonrpc?: string
    id?: number
    method?: string
    params?: unknown
    result?: unknown
    error?: unknown
}

function toTimestamp(line: RawStoredLine): number {
    if (typeof line.ts === 'number') {
        return line.ts
    }
    if (line.timestamp) {
        const parsed = new Date(line.timestamp).getTime()
        if (!Number.isNaN(parsed)) {
            return parsed
        }
    }
    return 0
}

/** Pull a JSON-RPC message out of a stored line (wrapped or bare). */
function extractMessage(line: RawStoredLine): JsonRpcMessage | null {
    const src = line.notification ?? line
    const hasMethod = typeof src.method === 'string'
    const hasId = typeof src.id === 'number'
    const hasResult = src.result !== undefined || src.error !== undefined

    if (!hasMethod && !hasId && !hasResult) {
        return null
    }

    const message: Record<string, unknown> = {}
    if (src.jsonrpc) {
        message.jsonrpc = src.jsonrpc
    }
    if (hasId) {
        message.id = src.id
    }
    if (hasMethod) {
        message.method = src.method
    }
    if ('params' in src && src.params !== undefined) {
        message.params = src.params
    }
    if (src.result !== undefined) {
        message.result = src.result
    }
    if (src.error !== undefined) {
        message.error = src.error
    }
    return message as unknown as JsonRpcMessage
}

/** Convert a single parsed stored line into an `AcpMessage`, or null to skip. */
function lineToAcpMessage(line: RawStoredLine): AcpMessage | null {
    const message = extractMessage(line)
    if (!message) {
        return null
    }
    normalizeSessionUpdateRawOutput(message)
    return {
        type: 'acp_message',
        ts: toTimestamp(line),
        message,
    }
}

/**
 * Parse a single ACP event object (e.g. from an SSE stream) into an
 * `AcpMessage`. Mirrors `lineToAcpMessage` for the real-time path. Accepts
 * either the stored-entry envelope or a bare JSON-RPC message.
 */
export function parseSessionLogEvent(event: Record<string, unknown>, ts?: number): AcpMessage | null {
    const line = event as RawStoredLine
    if (typeof ts === 'number') {
        line.ts = ts
    }
    return lineToAcpMessage(line)
}

export function parseSessionLogs(logs: string): AcpMessage[] {
    if (!logs) {
        return []
    }

    const events: AcpMessage[] = []
    const lines = logs.split('\n')

    for (const rawLine of lines) {
        const trimmed = rawLine.trim()
        if (!trimmed) {
            continue
        }
        try {
            const parsed = JSON.parse(trimmed) as RawStoredLine
            const event = lineToAcpMessage(parsed)
            if (event) {
                events.push(event)
            }
        } catch {
            // Skip malformed lines
        }
    }

    return events
}
