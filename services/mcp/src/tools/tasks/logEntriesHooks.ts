import type { ToolHooks } from '@/tools/tool-hooks'

function parseLogEntry(line: string): unknown {
    try {
        return JSON.parse(line)
    } catch {
        return { unparseable_line: line }
    }
}

function logEntries(body: unknown): unknown[] {
    if (typeof body !== 'string') {
        throw new Error('Expected the run log page as JSONL text.')
    }
    return body
        .split('\n')
        .filter((line) => line.trim() !== '')
        .map(parseLogEntry)
}

export default {
    afterResponse: (_context, _params, result) => logEntries(result),
} satisfies ToolHooks<unknown>
