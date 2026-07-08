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

export function sanitizeHeaderValue(value?: string): string | undefined {
    if (!value) {
        return undefined
    }
    // Strip control characters, then trim and truncate
    const sanitised = value
        .replace(/[\x00-\x1f\x7f]/g, '')
        .trim()
        .slice(0, MAX_HEADER_VALUE_LENGTH)
    return sanitised || undefined
}

export type McpMode = 'tools' | 'cli'

// Caller-supplied selection between the tool-based MCP (each PostHog tool registered
// individually) and the CLI-based MCP (a single `posthog` CLI-like tool that wraps
// all tools). Anything other than `tools` or `cli` returns undefined and lets the
// auto-detection in `MCP.init()` pick.
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
