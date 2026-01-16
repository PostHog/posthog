const DISTINCT_ID_KEYS = ['distinct_id', 'distinctId', 'distinctID']
const SESSION_ID_KEYS = ['session_id', 'session.id', 'sessionId', 'sessionID']

// UUID v4 pattern
const UUID_REGEX = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

export function isDistinctIdKey(key: string): boolean {
    return DISTINCT_ID_KEYS.includes(key)
}

export function isSessionIdKey(key: string): boolean {
    return SESSION_ID_KEYS.includes(key)
}

export function looksLikeUUID(value: string): boolean {
    return UUID_REGEX.test(value)
}

export function shouldLinkToPersonPage(key: string, value: string): boolean {
    return isDistinctIdKey(key) && !looksLikeUUID(value)
}

export function shouldLinkToSessionReplay(key: string, value: string): boolean {
    // Similar logic to ViewRecordingButton - check if session ID exists and is meaningful
    return isSessionIdKey(key) && !!value && value.trim().length > 0
}
