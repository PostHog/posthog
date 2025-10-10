import crypto from 'node:crypto'

export function hash(data: string) {
    // Use PBKDF2 with sufficient computational effort for security
    // 100,000 iterations provides good security while maintaining reasonable performance
    const salt = crypto.createHash('sha256').update('posthog_mcp_salt').digest()
    return crypto.pbkdf2Sync(data, salt, 100000, 32, 'sha256').toString('hex')
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
