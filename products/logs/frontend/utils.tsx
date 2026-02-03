const DISTINCT_ID_KEYS = ['distinct.id', 'distinct_id', 'distinctId', 'distinctID']
const SESSION_ID_KEYS = ['session.id', 'session_id', 'sessionId', 'sessionID', '$session_id']

export function isDistinctIdKey(key: string): boolean {
    return DISTINCT_ID_KEYS.includes(key)
}

export function isSessionIdKey(key: string): boolean {
    return SESSION_ID_KEYS.includes(key)
}
