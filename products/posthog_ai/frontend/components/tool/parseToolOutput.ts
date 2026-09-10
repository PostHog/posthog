import { decode } from '@toon-format/toon'

import type { ToolCallMessage } from 'products/posthog_ai/frontend/types/toolTypes'

import { parseExecCall, parseExecCommand } from './posthogExecDisplay'
import { getAllText } from './toolContentUtils'

/**
 * Generic tool-output parsing, kept free of the entity-specific extractors so a product widget can
 * parse a tool's result through the `api/tools` facade without pulling the recordings / error-tracking
 * conversion deps that `widgets/extractors.ts` carries.
 */

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
 * Best-effort record from a tool call's `rawOutput`. Objects pass through; strings are parsed per the
 * exec `call` output contract: `--json` means the server responded with `JSON.stringify`, otherwise
 * TOON (`services/mcp/src/lib/response.ts`). The off-order format is still tried as a fallback, and
 * anything unparseable (or empty) resolves to null so the caller falls back to the generic card.
 * An MCP result envelope is unwrapped first, preferring its structured content because the text can be
 * an optimized summary without the entity fields.
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
