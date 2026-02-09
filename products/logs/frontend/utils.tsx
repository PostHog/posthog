const DISTINCT_ID_KEYS = [
    'distinct.id',
    'distinct_id',
    'distinctId',
    'distinctID',
    'posthogDistinctId',
    'posthogDistinctID',
    'posthog_distinct_id',
    'posthog.distinct.id',
    'posthog.distinct_id',
]
const SESSION_ID_KEYS = [
    'session.id',
    'session_id',
    'sessionId',
    'sessionID',
    '$session_id',
    'posthogSessionId',
    'posthogSessionID',
    'posthog_session_id',
    'posthog.session.id',
    'posthog.session_id',
]

function matchesKey(key: string, candidates: string[]): boolean {
    return candidates.some((candidate) => key === candidate || key.endsWith(`.${candidate}`))
}

export function isDistinctIdKey(key: string): boolean {
    return matchesKey(key, DISTINCT_ID_KEYS)
}

export function isSessionIdKey(key: string): boolean {
    return matchesKey(key, SESSION_ID_KEYS)
}
