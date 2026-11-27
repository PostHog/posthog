import { uuid } from 'lib/utils/dom'

// pinned: URL search param, the editors save it on the first create as entry_attempt_id
export const ATTEMPT_PREFILL_PARAM = 'attempt'

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

const attempts = new Map<string, string>()

const attemptKey = (source: string, destination: string): string => `${source}\n${destination}`

export function startMessageAudienceAttempt(source: string, destination: string): string {
    const attemptId = uuid()
    attempts.set(attemptKey(source, destination), attemptId)
    return attemptId
}

export function messageAudienceAttempt(source: string | undefined, destination: string): string | undefined {
    return source ? attempts.get(attemptKey(source, destination)) : undefined
}

export function parseAttemptPrefill(raw: unknown): string | undefined {
    return typeof raw === 'string' && UUID_PATTERN.test(raw) ? raw : undefined
}
