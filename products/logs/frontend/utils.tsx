const DISTINCT_ID_KEYS = ['distinct.id', 'distinct_id', 'distinctId', 'distinctID']

export function isDistinctIdKey(key: string): boolean {
    return DISTINCT_ID_KEYS.includes(key)
}
