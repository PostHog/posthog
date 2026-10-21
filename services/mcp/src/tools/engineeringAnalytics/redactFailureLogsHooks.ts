import {
    PRIVATE_KEY_FOOTER_PATTERN,
    PRIVATE_KEY_HEADER_PATTERN,
    REDACTED_VALUE,
    redactCredentials,
} from '@/lib/credential-redaction'
import { isRecord } from '@/lib/plain-object'
import type { ToolHooks } from '@/tools/tool-hooks'
import type { Context } from '@/tools/types'

function lastIndexOf(pattern: RegExp, text: string): number {
    return Array.from(text.matchAll(pattern)).at(-1)?.index ?? -1
}

// The emitter stores one log line per record, so a private key spans several lines of a job.
function redactPrivateKeyLines(lines: unknown[]): unknown[] {
    let insideKey = false
    return lines.map((line) => {
        if (!isRecord(line) || typeof line.text !== 'string') {
            return line
        }
        let text = line.text
        if (insideKey) {
            const footer = text.search(PRIVATE_KEY_FOOTER_PATTERN)
            if (footer >= 0) {
                text = REDACTED_VALUE + text.slice(footer)
                insideKey = false
            } else if (line.original_line != null) {
                // Omission markers have no original line and carry only a line count.
                text = REDACTED_VALUE
            }
        }
        const header = lastIndexOf(PRIVATE_KEY_HEADER_PATTERN, text)
        if (header >= 0 && lastIndexOf(PRIVATE_KEY_FOOTER_PATTERN, text) < header) {
            insideKey = true
        }
        return { ...line, text }
    })
}

// CI log lines are build output, so they can print environment values and keys that GitHub did not mask.
function afterResponse(_context: Context, _params: unknown, result: unknown): unknown {
    if (isRecord(result) && Array.isArray(result.jobs)) {
        result = {
            ...result,
            jobs: result.jobs.map((job) =>
                isRecord(job) && Array.isArray(job.lines) ? { ...job, lines: redactPrivateKeyLines(job.lines) } : job
            ),
        }
    }
    return redactCredentials(result)
}

export default { afterResponse } satisfies ToolHooks<unknown>
