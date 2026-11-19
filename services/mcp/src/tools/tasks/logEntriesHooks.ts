import { isRecord } from '@/lib/plain-object'
import type { ToolHooks } from '@/tools/tool-hooks'

function parseLogEntry(line: string): unknown {
    try {
        return JSON.parse(line)
    } catch {
        return { unparseable_line: line }
    }
}

function logEntries(result: unknown): unknown[] {
    if (typeof result === 'string') {
        return result
            .split('\n')
            .filter((line) => line.trim() !== '')
            .map(parseLogEntry)
    }
    if (isRecord(result) && Object.keys(result).length === 0) {
        return []
    }
    return [result]
}

export default {
    afterResponse: (_context, _params, result) => logEntries(result),
} satisfies ToolHooks<unknown>
