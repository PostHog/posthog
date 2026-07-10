import type { ReplayObservationApi } from '../generated/api.schemas'

export function readModelOutput(obs: ReplayObservationApi): Record<string, unknown> | null {
    const out = obs.scanner_result?.model_output
    return out && typeof out === 'object' ? (out as Record<string, unknown>) : null
}

export function readScore(obs: ReplayObservationApi): number | null {
    const raw = readModelOutput(obs)?.score
    return typeof raw === 'number' ? raw : null
}

export type MonitorVerdict = 'yes' | 'no' | 'inconclusive'

export function readVerdict(obs: ReplayObservationApi): MonitorVerdict | null {
    const raw = readModelOutput(obs)?.verdict
    return raw === 'yes' || raw === 'no' || raw === 'inconclusive' ? raw : null
}

export function readReasoning(obs: ReplayObservationApi): string | null {
    const raw = readModelOutput(obs)?.reasoning
    return typeof raw === 'string' && raw ? raw : null
}

function readStringArray(value: unknown): string[] {
    if (!Array.isArray(value)) {
        return []
    }
    return value.filter((t): t is string => typeof t === 'string')
}

/** Tags from the scanner's configured vocabulary. */
export function readFixedTags(obs: ReplayObservationApi): string[] {
    return readStringArray(readModelOutput(obs)?.tags)
}

/** Tags the model emits outside the vocabulary when `allow_freeform_tags` is on. */
export function readFreeformTags(obs: ReplayObservationApi): string[] {
    return readStringArray(readModelOutput(obs)?.tags_freeform)
}

export function readTags(obs: ReplayObservationApi): string[] {
    return [...readFixedTags(obs), ...readFreeformTags(obs)]
}
