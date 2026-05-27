import type { ReplayObservationApi } from '../generated/api.schemas'

/** Narrow the model_output JSON blob to a string-keyed record, or null when missing/malformed. */
export function readModelOutput(obs: ReplayObservationApi): Record<string, unknown> | null {
    const out = obs.scanner_result?.model_output
    return out && typeof out === 'object' ? (out as Record<string, unknown>) : null
}

export function readScore(obs: ReplayObservationApi): number | null {
    const raw = readModelOutput(obs)?.score
    return typeof raw === 'number' ? raw : null
}

export function readVerdict(obs: ReplayObservationApi): boolean | null {
    const raw = readModelOutput(obs)?.verdict
    return typeof raw === 'boolean' ? raw : null
}

function readStringArray(value: unknown): string[] {
    if (!Array.isArray(value)) {
        return []
    }
    return value.filter((t): t is string => typeof t === 'string')
}

/** Fixed tags only — those from the scanner's configured vocabulary. */
export function readFixedTags(obs: ReplayObservationApi): string[] {
    return readStringArray(readModelOutput(obs)?.tags)
}

/** Freeform tags only — emitted by the model when `allow_freeform_tags` is on. */
export function readFreeformTags(obs: ReplayObservationApi): string[] {
    return readStringArray(readModelOutput(obs)?.tags_freeform)
}

/** All tags emitted by the model — fixed + freeform combined. */
export function readTags(obs: ReplayObservationApi): string[] {
    return [...readFixedTags(obs), ...readFreeformTags(obs)]
}

export function readConfidence(obs: ReplayObservationApi): number | null {
    const raw = readModelOutput(obs)?.confidence
    return typeof raw === 'number' ? raw : null
}
