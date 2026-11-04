import {
    type CredentialNameRule,
    PRIVATE_KEY_FOOTER_PATTERN,
    PRIVATE_KEY_HEADER_PATTERN,
    REDACTED_VALUE,
    decodeEscapes,
    redactCredentials,
} from '@/lib/credential-redaction'
import { isRecord } from '@/lib/plain-object'
import type { ToolHooks } from '@/tools/tool-hooks'
import type { Context } from '@/tools/types'

// CI output prints names such as `key`, `code`, `session` and `input_tokens` for diagnostics, not credentials.
const CI_CREDENTIAL_NAME_FRAGMENTS = ['apikey', 'secret', 'password', 'passwd', 'credential', 'privatekey', 'signature']
const CI_CREDENTIAL_NAMES = new Set(['pwd', 'authorization', 'jwt', 'sig', 'sessionid'])

const isCiCredentialName: CredentialNameRule = (name) =>
    CI_CREDENTIAL_NAMES.has(name) ||
    name.endsWith('token') ||
    CI_CREDENTIAL_NAME_FRAGMENTS.some((part) => name.includes(part))

function lastIndexOf(pattern: RegExp, text: string): number {
    return Array.from(text.matchAll(pattern)).at(-1)?.index ?? -1
}

// A header followed by more text on its line is a string in code, such as an assertion, not the start of a key.
const KEY_OPENING_PATTERN = new RegExp(`${PRIVATE_KEY_HEADER_PATTERN.source}\\s*$`)
// Thinning can move a key header or footer into an omitted gap, so a bare base64 body line counts too.
const KEY_BODY_LINE_PATTERN = /^\s*(?=[^\s]*[A-Z])(?=[^\s]*[a-z])(?=[^\s]*\d)[A-Za-z0-9+/]{40,}={0,2}\s*$/
// The last body line of a key is shorter than the others, so it only counts directly after a body line.
const KEY_LAST_LINE_PATTERN = /^\s*[A-Za-z0-9+/]{1,63}={0,2}\s*$/
// The log fetcher inserts this marker with a line number where it drops the middle of an oversized log.
const TRUNCATION_MARKER = '... [log truncated] ...'

// The emitter stores one log line per record, so a private key spans several lines of a job.
function redactPrivateKeyLines(lines: unknown[]): unknown[] {
    let insideKey = false
    let afterBodyLine = false
    let lastGap = -1
    const redacted: unknown[] = []
    for (const line of lines) {
        if (!isRecord(line) || typeof line.text !== 'string') {
            redacted.push(line)
            continue
        }
        const plain = decodeEscapes(line.text) ?? line.text
        // Thinning omission markers have no original line and carry only a line count.
        if (line.original_line == null || plain.trim() === TRUNCATION_MARKER) {
            // A gap can hide the footer, so the lines after it are body lines only by their shape.
            insideKey = false
            afterBodyLine = false
            lastGap = redacted.length
            redacted.push(line)
            continue
        }
        let text = line.text
        let isBodyLine = false
        const footer = plain.search(PRIVATE_KEY_FOOTER_PATTERN)
        if (footer >= 0 && lastIndexOf(PRIVATE_KEY_HEADER_PATTERN, plain) < 0) {
            text = REDACTED_VALUE + plain.slice(footer)
            if (!insideKey && lastGap >= 0) {
                // The header is in the omitted gap, so the body runs from the gap to this footer.
                for (let i = lastGap + 1; i < redacted.length; i++) {
                    redacted[i] = { ...(redacted[i] as Record<string, unknown>), text: REDACTED_VALUE }
                }
            }
            insideKey = false
        } else if (
            insideKey ||
            KEY_BODY_LINE_PATTERN.test(plain) ||
            (afterBodyLine && KEY_LAST_LINE_PATTERN.test(plain))
        ) {
            text = REDACTED_VALUE
            isBodyLine = KEY_BODY_LINE_PATTERN.test(plain)
        }
        if (KEY_OPENING_PATTERN.test(plain)) {
            insideKey = true
        }
        afterBodyLine = isBodyLine
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
    return redactCredentials(result, isCiCredentialName)
}

export default { afterResponse } satisfies ToolHooks<unknown>
