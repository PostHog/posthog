// pinned: URL search param, the editors save it on the first create as entry_attempt_id
export const ATTEMPT_PREFILL_PARAM = 'attempt'

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

export function parseAttemptPrefill(raw: unknown): string | undefined {
    return typeof raw === 'string' && UUID_PATTERN.test(raw) ? raw : undefined
}
