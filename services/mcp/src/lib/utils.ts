import crypto from 'node:crypto'

import { env } from '@/lib/env'

export function hash(data: string): string {
    // Use PBKDF2 with sufficient computational effort for security
    // 100,000 iterations provides good security while maintaining reasonable performance
    const salt = crypto.createHash('sha256').update('posthog_mcp_salt').digest()
    return crypto.pbkdf2Sync(data, salt, 100000, 32, 'sha256').toString('hex')
}

// Extract the API token from a request. Prefers the `Authorization: Bearer
// <token>` header. In dev/test only, falls back to a `?token=` query param for
// clients that can only customize the URL, not request headers (e.g. MCP UI
// apps in an iframe). The fallback uses a positive allowlist so it fails closed
// when NODE_ENV is unset (e.g. on Cloudflare Workers) — keeping tokens out of
// URLs (logs, referrers, history) in production.
export function extractBearerToken(request: Request): string | undefined {
    const headerToken = request.headers.get('Authorization')?.split(' ')[1]
    if (headerToken) {
        return headerToken
    }
    if (env.NODE_ENV === 'development' || env.NODE_ENV === 'test') {
        return new URL(request.url).searchParams.get('token') || undefined
    }
    return undefined
}

// Redact an API token for logs: keep only the last 4 chars, mask the rest.
// Tokens of 4 chars or fewer (or empty) are fully masked so nothing useful leaks.
export function redactToken(token: string): string {
    if (token.length <= 4) {
        return '****'
    }
    return `****${token.slice(-4)}`
}

export function formatPrompt(template: string, vars: Record<string, string>): string {
    // Use a function replacement so `$` sequences (`$&`, `$$`, `` $` ``, `$'`) inside a
    // value are NOT interpreted as replacement-pattern escapes. Otherwise values containing
    // e.g. `` `$` `` (common in PostHog docs that mention `$pageview`) would splice the
    // template prefix/suffix into the output and look like a double injection.
    return Object.entries(vars)
        .reduce((result, [key, value]) => result.replaceAll(`{${key}}`, () => value ?? ''), template)
        .trim()
}

const MAX_HEADER_VALUE_LENGTH = 1000

// Non-ASCII punctuation that turns up constantly in human-authored names (OAuth app names,
// MCP client names) and has an obvious ASCII stand-in. Folding these first keeps the value
// legible: an em-dash separator becomes " - " rather than vanishing and joining two words.
// Spelled as escapes rather than literals on purpose: these are exactly the characters you
// cannot tell apart by eye, and the outage this guards against was one of them in a string.
const ASCII_PUNCTUATION_FOLDS: ReadonlyArray<readonly [RegExp, string]> = [
    [/[\u2010-\u2015\u2212]/g, '-'], // hyphens, en/em dashes, minus sign
    [/[\u2018-\u201b\u2032]/g, "'"], // single curly quotes, prime
    [/[\u201c-\u201f\u2033]/g, '"'], // double curly quotes, double prime
    [/\u2026/g, '...'], // horizontal ellipsis
    [/[\u00a0\u2007\u202f]/g, ' '], // non-breaking spaces; keep the word separation
]

/**
 * Normalise a caller-supplied value for use as an outbound HTTP header.
 *
 * Header values are ByteStrings, so a single code point above 255 makes `fetch` throw
 * `TypeError: Cannot convert argument to a ByteString ...` before the request is even sent —
 * an em-dash in an OAuth app's registered name is enough to fail every API call made on its
 * behalf. These values are attribution-only, so restricting them to printable ASCII costs
 * nothing: fold what has a sensible ASCII equivalent and drop the rest. The result is always
 * a legal header value, and always safe to log.
 */
export function sanitizeHeaderValue(value?: string): string | undefined {
    if (!value) {
        return undefined
    }
    let sanitised = value
    for (const [pattern, replacement] of ASCII_PUNCTUATION_FOLDS) {
        sanitised = sanitised.replace(pattern, replacement)
    }
    sanitised = sanitised
        // Compatibility-decompose so accented letters keep their base character: "Café"
        // becomes "Cafe" once the trailing combining mark is dropped below, not "Caf".
        .normalize('NFKD')
        // Drop everything that isn't printable ASCII — non-Latin-1 code points (the
        // ByteString hazard), leftover combining marks, control characters, and DEL.
        .replace(/[^\x20-\x7e]/g, '')
        // Collapse space runs left behind by dropped characters.
        .replace(/ {2,}/g, ' ')
        .trim()
        .slice(0, MAX_HEADER_VALUE_LENGTH)
        // Truncation can land on a space; header values must not end in whitespace.
        .trim()
    return sanitised || undefined
}

export type McpMode = 'tools' | 'cli'

// Caller-supplied selection between the tool-based MCP (each PostHog tool registered
// individually) and the CLI-based MCP (a single `posthog` CLI-like tool that wraps
// all tools). Anything other than `tools` or `cli` returns undefined and lets
// `resolveMode` pick: cli by default, tools for allow-listed clients (Cursor, ChatGPT).
export function parseMcpMode(raw: string | null | undefined): McpMode | undefined {
    const value = raw?.trim().toLowerCase()
    return value === 'tools' ? 'tools' : value === 'cli' ? 'cli' : undefined
}

export function getSearchParamsFromRecord(
    params: Record<string, string | number | boolean | undefined>
): URLSearchParams {
    const searchParams = new URLSearchParams()

    for (const [key, value] of Object.entries(params)) {
        if (value !== undefined) {
            searchParams.append(key, String(value))
        }
    }

    return searchParams
}
