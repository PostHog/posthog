import crypto from 'node:crypto'

export function hash(data: string): string {
    // Use PBKDF2 with sufficient computational effort for security
    // 100,000 iterations provides good security while maintaining reasonable performance
    const salt = crypto.createHash('sha256').update('posthog_mcp_salt').digest()
    return crypto.pbkdf2Sync(data, salt, 100000, 32, 'sha256').toString('hex')
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
