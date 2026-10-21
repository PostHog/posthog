import { assignKey, isRecord } from '@/lib/plain-object'

const REDACTED_VALUE = '[REDACTED]'
const MAX_ENCODING_LAYERS = 8
const CREDENTIAL_NAME_FRAGMENTS = ['apikey', 'token', 'secret', 'password', 'passwd', 'credential', 'signature']
const CREDENTIAL_NAMES = new Set(['key', 'pwd', 'auth', 'authorization', 'sig', 'code', 'jwt', 'session', 'sessionid'])

const ASSIGNMENT_PATTERN =
    /(?:^|(?<=[?&;\s{,("'\\]))(?:"((?:\\.|[^"\\])*)"|'((?:\\.|[^'\\])*)'|([A-Za-z0-9_%.[\]-]+))\s*([=:])\s*/g
const QUOTED_VALUE_PATTERN = /^("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')/
const URL_PASSWORD_PATTERN = /\b[a-z][a-z\d+.-]*:\/\/[^\s/"'<>\\]*@/gi
// Project tokens (phc_) are public; these prefixes identify private tokens in posthog/models/utils.py.
const POSTHOG_TOKEN_PATTERN = /\b(?:phx|phs|pha|phr)_([A-Za-z0-9_-]{16,})/g
const BEARER_PATTERN = /\bBearer\s+([^\s"'\\,;}]+)/gi
const ESCAPE_PATTERN = /%([0-9a-f]{2})|\\u([0-9a-f]{4})|\\(["'\\/])/gi

function decodeEscape(
    _match: string,
    percent: string | undefined,
    unicode: string | undefined,
    escaped: string
): string {
    return percent || unicode ? String.fromCharCode(Number.parseInt(percent || unicode!, 16)) : escaped
}

function isCredentialName(name: string): boolean {
    let decoded = name
    let layers = 0
    for (;;) {
        const next = decoded.replace(ESCAPE_PATTERN, decodeEscape)
        if (next === decoded) {
            break
        }
        if (++layers > MAX_ENCODING_LAYERS) {
            return true
        }
        decoded = next
    }
    const normalized = decoded.toLowerCase().replace(/[^a-z0-9]/g, '')
    return CREDENTIAL_NAMES.has(normalized) || CREDENTIAL_NAME_FRAGMENTS.some((part) => normalized.includes(part))
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

function findCredentialRanges(text: string): RedactionRange[] {
    const ranges: RedactionRange[] = []
    for (const match of text.matchAll(ASSIGNMENT_PATTERN)) {
        if (!isCredentialName(match[1] ?? match[2] ?? match[3]!)) {
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
    for (const pattern of [POSTHOG_TOKEN_PATTERN, BEARER_PATTERN]) {
        for (const match of text.matchAll(pattern)) {
            const end = match.index + match[0].length
            ranges.push({ start: end - match[1]!.length, end })
        }
    }
    return ranges
}

export function redactCredentialsInText(text: string): string {
    const ranges: RedactionRange[] = []
    let decoded = text
    let offsets = Array.from({ length: text.length + 1 }, (_, index) => index)
    let layers = 0
    for (;;) {
        for (const range of findCredentialRanges(decoded)) {
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

export function redactCredentials(value: unknown): unknown {
    if (typeof value === 'string') {
        return redactCredentialsInText(value)
    }
    if (Array.isArray(value)) {
        return value.map(redactCredentials)
    }
    if (isRecord(value)) {
        const redacted: Record<string, unknown> = {}
        for (const [key, entry] of Object.entries(value)) {
            assignKey(
                redacted,
                redactCredentialsInText(key),
                isCredentialName(key) ? REDACTED_VALUE : redactCredentials(entry)
            )
        }
        return redacted
    }
    return value
}
