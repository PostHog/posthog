import crypto from 'node:crypto'

export function hash(data: string): string {
    // Use PBKDF2 with sufficient computational effort for security
    // 100,000 iterations provides good security while maintaining reasonable performance
    const salt = crypto.createHash('sha256').update('posthog_mcp_salt').digest()
    return crypto.pbkdf2Sync(data, salt, 100000, 32, 'sha256').toString('hex')
}

export function formatPrompt(template: string, vars: Record<string, string>): string {
    return Object.entries(vars)
        .reduce((result, [key, value]) => result.replaceAll(`{${key}}`, value), template)
        .trim()
}

const MAX_USER_AGENT_LENGTH = 1000

export function sanitizeUserAgent(userAgent?: string): string | undefined {
    if (!userAgent) {
        return undefined
    }
    // Strip control characters, then trim and truncate
    const sanitised = userAgent
        .replace(/[\x00-\x1f\x7f]/g, '')
        .trim()
        .slice(0, MAX_USER_AGENT_LENGTH)
    return sanitised || undefined
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
