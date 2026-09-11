import { decode } from '@toon-format/toon'

import type { ToolCallMessage } from '../../types/toolTypes'
import { parseExecCall, parseExecCommand } from './posthogExecDisplay'
import { getAllText } from './toolContentUtils'

export function asRecord(value: unknown): Record<string, unknown> | null {
    return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : null
}

function parseJsonRecord(text: string): Record<string, unknown> | null {
    try {
        return asRecord(JSON.parse(text))
    } catch {
        return null
    }
}

function parseToonRecord(text: string): Record<string, unknown> | null {
    // TOON decode is lenient — JSON text doesn't throw, it mangles into a garbage record — so
    // anything that reads as JSON syntax must never reach it.
    if (/^[[{]/.test(text)) {
        return null
    }
    try {
        return asRecord(decode(text))
    } catch {
        return null
    }
}

function unwrapToolOutput(rawOutput: unknown): unknown {
    const envelope = asRecord(rawOutput)
    if (envelope?.isError === true) {
        return null
    }
    const structuredContent = asRecord(envelope?.structuredContent)
    if (structuredContent) {
        return structuredContent
    }
    // Entity payloads can also have a content array, so only unwrap the MCP envelope's top-level shape.
    if (
        !envelope ||
        !Object.keys(envelope).every((key) => ['content', 'structuredContent', 'isError', '_meta'].includes(key))
    ) {
        return rawOutput
    }
    return Array.isArray(envelope.content) ? getAllText(envelope.content).join('\n') : rawOutput
}

/**
 * Prefer structured content because the text can be an optimized summary without the entity fields.
 */
export function parseToolOutputRecord(message: ToolCallMessage): Record<string, unknown> | null {
    const rawOutput = unwrapToolOutput(message.rawOutput)
    const direct = asRecord(rawOutput)
    if (direct) {
        return direct
    }
    if (typeof rawOutput !== 'string') {
        return null
    }
    const text = rawOutput.trim()
    if (!text) {
        return null
    }
    const command = typeof message.rawInput.command === 'string' ? message.rawInput.command : ''
    const { verb, rest } = parseExecCommand(command)
    const forceJson = verb === 'call' && parseExecCall(rest).forceJson
    const attempts = forceJson ? [parseJsonRecord, parseToonRecord] : [parseToonRecord, parseJsonRecord]
    for (const attempt of attempts) {
        const record = attempt(text)
        // decode('') and JSON '{}' both yield {}, which carries nothing a widget can render.
        if (record && Object.keys(record).length > 0) {
            return record
        }
    }
    return null
}
