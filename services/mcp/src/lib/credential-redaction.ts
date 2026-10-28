import { assignKey, isRecord } from '@/lib/plain-object'

export const REDACTED_VALUE = '[REDACTED]'
const MAX_ENCODING_LAYERS = 8
const CREDENTIAL_NAME_FRAGMENTS = ['apikey', 'token', 'secret', 'password', 'passwd', 'credential', 'signature']
const CREDENTIAL_NAMES = new Set(['key', 'pwd', 'auth', 'authorization', 'sig', 'code', 'jwt', 'session', 'sessionid'])

// Receives a name lowercased with every non-alphanumeric character removed, for example `accesstoken`.
export type CredentialNameRule = (name: string) => boolean

export const isLogCredentialName: CredentialNameRule = (name) =>
    CREDENTIAL_NAMES.has(name) || CREDENTIAL_NAME_FRAGMENTS.some((part) => name.includes(part))

const ASSIGNMENT_PATTERN =
    /(?:^|(?<=[?&;\s{,("'\\]))(?:"((?:\\.|[^"\\])*)"|'((?:\\.|[^'\\])*)'|([A-Za-z0-9_%.[\]-]+))\s*([=:])\s*/g
const QUOTED_VALUE_PATTERN = /^("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')/
const URL_PASSWORD_PATTERN = /\b[a-z][a-z\d+.-]*:\/\/[^\s/"'<>\\]*@/gi
// Project tokens (phc_) are public; these prefixes identify private tokens in posthog/models/utils.py.
const POSTHOG_TOKEN_PATTERN = /\b(?:phx|phs|pha|phr)_([A-Za-z0-9_-]{16,})/g
const BEARER_PATTERN = /\bBearer\s+([^\s"'\\,;}]+)/gi
// The label check is a lookahead because two overlapping repeats around `PRIVATE KEY` backtrack quadratically.
const PRIVATE_KEY_LABEL = '(?=[A-Z0-9 ]*?PRIVATE KEY)[A-Z0-9 ]*-----'
export const PRIVATE_KEY_HEADER_PATTERN = new RegExp(`-----BEGIN ${PRIVATE_KEY_LABEL}`, 'g')
export const PRIVATE_KEY_FOOTER_PATTERN = new RegExp(`-----END ${PRIVATE_KEY_LABEL}`, 'g')
// The body runs to the end of the string when the footer is absent, so a key cut off mid-string stays masked.
const PRIVATE_KEY_PATTERN = new RegExp(
    `(${PRIVATE_KEY_HEADER_PATTERN.source})([\\s\\S]*?)(?:${PRIVATE_KEY_FOOTER_PATTERN.source}|$)`,
    'g'
)
// Classic, OAuth, user-to-server, server-to-server, refresh and fine-grained GitHub tokens.
const GITHUB_TOKEN_PATTERN = /\b(?:gh[pousr]|github_pat)_([A-Za-z0-9_]{36,})/g
const FLAG_VALUE_PATTERN =
    /(?<=^|\s)--([A-Za-z0-9_-]*(?:password|passwd|token|secret|api[_-]?key))\s+(?!-)("[^"]*"|'[^']*'|[^\s"']+)/gi
const USER_PASSWORD_FLAG_PATTERN = /(?<=^|\s)(?:-u|--user)(?:\s+|=)?(["']?)([^\s:"']+):([^\s"']+)\1/g
const ESCAPE_PATTERN = /%([0-9a-f]{2})|\\u([0-9a-f]{4})|\\(["'\\/])/gi

function decodeEscape(
    _match: string,
    percent: string | undefined,
    unicode: string | undefined,
    escaped: string
): string {
    return percent || unicode ? String.fromCharCode(Number.parseInt(percent || unicode!, 16)) : escaped
}

// Returns null when the text has more than MAX_ENCODING_LAYERS layers of encoding.
export function decodeEscapes(text: string): string | null {
    let decoded = text
    let layers = 0
    for (;;) {
        const next = decoded.replace(ESCAPE_PATTERN, decodeEscape)
        if (next === decoded) {
            return decoded
        }
        if (++layers > MAX_ENCODING_LAYERS) {
            return null
        }
        decoded = next
    }
}

function isCredentialName(name: string, rule: CredentialNameRule): boolean {
    const decoded = decodeEscapes(name)
    return decoded === null || rule(decoded.toLowerCase().replace(/[^a-z0-9]/g, ''))
}

interface RedactionRange {
    start: number
    end: number
}

function containerLength(text: string): number {
    let depth = 0
    for (const match of text.matchAll(/"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[{}[\]]/g)) {
        if (match[0] === '{' || match[0] === '[') {
            depth++
        } else if (match[0] === '}' || match[0] === ']') {
            if (--depth === 0) {
                return match.index + 1
            }
        }
    }
    return text.length
}

function findCredentialRanges(text: string, rule: CredentialNameRule): RedactionRange[] {
    const ranges: RedactionRange[] = []
    for (const match of text.matchAll(ASSIGNMENT_PATTERN)) {
        if (!isCredentialName(match[1] ?? match[2] ?? match[3]!, rule)) {
            continue
        }
        const start = match.index + match[0].length
        const rest = text.slice(start)
        const quoted = rest.match(QUOTED_VALUE_PATTERN)
        if (quoted) {
            ranges.push({ start: start + 1, end: start + quoted[0].length - 1 })
        } else if (/^[{[]/.test(rest)) {
            ranges.push({ start, end: start + containerLength(rest) })
        } else {
            const value = rest.startsWith(REDACTED_VALUE)
                ? REDACTED_VALUE
                : rest.match(match[4] === '=' ? /^(?:\\(?!["'])|[^&;\s"'\\#<>])+/ : /^[^\r\n,}\]]+/)?.[0].trimEnd()
            if (value) {
                ranges.push({ start, end: start + value.length })
            }
        }
    }
    for (const match of text.matchAll(URL_PASSWORD_PATTERN)) {
        const userInfoStart = match.index + match[0].indexOf('://') + 3
        const passwordStart = text.indexOf(':', userInfoStart)
        const end = match.index + match[0].length - 1
        if (passwordStart >= userInfoStart && passwordStart < end) {
            ranges.push({ start: passwordStart + 1, end })
        }
    }
    for (const match of text.matchAll(PRIVATE_KEY_PATTERN)) {
        if (match[2]) {
            const start = match.index + match[1]!.length
            ranges.push({ start, end: start + match[2].length })
        }
    }
    for (const pattern of [POSTHOG_TOKEN_PATTERN, BEARER_PATTERN, GITHUB_TOKEN_PATTERN, FLAG_VALUE_PATTERN]) {
        for (const match of text.matchAll(pattern)) {
            const end = match.index + match[0].length
            ranges.push({ start: end - match.at(-1)!.length, end })
        }
    }
    for (const match of text.matchAll(USER_PASSWORD_FLAG_PATTERN)) {
        // `-u 1000:1000` is a Docker user and group id, not a credential.
        if (!/^\d+$/.test(match[2]!) || !/^\d+$/.test(match[3]!)) {
            const end = match.index + match[0].length - match[1]!.length
            ranges.push({ start: end - match[3]!.length, end })
        }
    }
    return ranges
}

export function redactCredentialsInText(text: string, rule: CredentialNameRule = isLogCredentialName): string {
    const ranges: RedactionRange[] = []
    let decoded = text
    let offsets = Array.from({ length: text.length + 1 }, (_, index) => index)
    let layers = 0
    for (;;) {
        for (const range of findCredentialRanges(decoded, rule)) {
            ranges.push({ start: offsets[range.start]!, end: offsets[range.end]! })
        }

        // Keep original offsets so decoding reveals nested credentials without rewriting unrelated log content.
        const nextOffsets: number[] = []
        let previous = 0
        const next = decoded.replace(ESCAPE_PATTERN, (match, percent, unicode, escaped, index: number) => {
            for (let i = previous; i <= index; i++) {
                nextOffsets.push(offsets[i]!)
            }
            previous = index + match.length
            return decodeEscape(match, percent, unicode, escaped)
        })
        if (next === decoded) {
            break
        }
        // Bound decoding work on untrusted logs; excessive nesting must not expose credentials.
        if (++layers > MAX_ENCODING_LAYERS) {
            return REDACTED_VALUE
        }
        for (let i = previous; i < offsets.length; i++) {
            nextOffsets.push(offsets[i]!)
        }
        decoded = next
        offsets = nextOffsets
    }

    const merged: RedactionRange[] = []
    for (const range of ranges.sort((a, b) => a.start - b.start)) {
        const last = merged.at(-1)
        if (last && range.start <= last.end) {
            last.end = Math.max(last.end, range.end)
        } else {
            merged.push({ ...range })
        }
    }
    let result = ''
    let previous = 0
    for (const { start, end } of merged) {
        result += text.slice(previous, start) + REDACTED_VALUE
        previous = end
    }
    return result + text.slice(previous)
}

export function redactCredentials(value: unknown, rule: CredentialNameRule = isLogCredentialName): unknown {
    if (typeof value === 'string') {
        return redactCredentialsInText(value, rule)
    }
    if (Array.isArray(value)) {
        return value.map((entry) => redactCredentials(entry, rule))
    }
    if (isRecord(value)) {
        const redacted: Record<string, unknown> = {}
        for (const [key, entry] of Object.entries(value)) {
            assignKey(
                redacted,
                redactCredentialsInText(key, rule),
                isCredentialName(key, rule) ? REDACTED_VALUE : redactCredentials(entry, rule)
            )
        }
        return redacted
    }
    return value
}
