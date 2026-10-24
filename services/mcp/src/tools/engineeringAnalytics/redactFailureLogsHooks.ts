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

// Thinning can move a key header or footer into an omitted gap, so a bare base64 body line counts too.
const KEY_BODY_LINE_PATTERN = /^\s*(?=[^\s]*[A-Z])(?=[^\s]*[a-z])(?=[^\s]*\d)[A-Za-z0-9+/]{40,}={0,2}\s*$/

// The emitter stores one log line per record, so a private key spans several lines of a job.
function redactPrivateKeyLines(lines: unknown[]): unknown[] {
    let insideKey = false
    let lastGap = -1
    const redacted: unknown[] = []
    for (const line of lines) {
        if (!isRecord(line) || typeof line.text !== 'string') {
            redacted.push(line)
            continue
        }
        // Omission markers have no original line and carry only a line count.
        const isOmissionMarker = line.original_line == null
        let text = line.text
        const footer = text.search(PRIVATE_KEY_FOOTER_PATTERN)
        if (footer >= 0 && lastIndexOf(PRIVATE_KEY_HEADER_PATTERN, text) < 0) {
            text = REDACTED_VALUE + text.slice(footer)
            if (!insideKey && lastGap >= 0) {
                // The header is in the omitted gap, so the body runs from the gap to this footer.
                for (let i = lastGap + 1; i < redacted.length; i++) {
                    redacted[i] = { ...(redacted[i] as Record<string, unknown>), text: REDACTED_VALUE }
                }
            }
            insideKey = false
        } else if ((insideKey && !isOmissionMarker) || KEY_BODY_LINE_PATTERN.test(text)) {
            text = REDACTED_VALUE
        }
        const header = lastIndexOf(PRIVATE_KEY_HEADER_PATTERN, text)
        if (header >= 0 && lastIndexOf(PRIVATE_KEY_FOOTER_PATTERN, text) < header) {
            insideKey = true
        }
        if (isOmissionMarker) {
            lastGap = redacted.length
        }
        redacted.push({ ...line, text })
    }
    return redacted
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
