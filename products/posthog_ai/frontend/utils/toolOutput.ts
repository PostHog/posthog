import { decode } from '@toon-format/toon'

import { parseExecCall, parseExecCommand } from './posthogExec'

function asRecord(value: unknown): Record<string, unknown> | null {
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

/**
 * Best-effort record from an MCP tool call's `rawOutput`. Objects pass through; strings are parsed
 * per the exec `call` output contract: `--json` means JSON, otherwise TOON. The off-order format is
 * still tried as a fallback, and anything unparseable (or empty) resolves to null.
 */
export function parseToolOutputRecord(
    rawOutput: unknown,
    rawInput: Record<string, unknown>
): Record<string, unknown> | null {
    const direct = asRecord(rawOutput)
    if (direct && Object.keys(direct).length > 0) {
        return direct
    }
    if (typeof rawOutput !== 'string' || !rawOutput.trim()) {
        return null
    }
    const command = typeof rawInput.command === 'string' ? rawInput.command : ''
    const { verb, rest } = parseExecCommand(command)
    const forceJson = verb === 'call' && parseExecCall(rest).forceJson
    const attempts = forceJson ? [parseJsonRecord, parseToonRecord] : [parseToonRecord, parseJsonRecord]
    for (const attempt of attempts) {
        const record = attempt(rawOutput.trim())
        if (record && Object.keys(record).length > 0) {
            return record
        }
    }
    return null
}
