import { dayjs } from 'lib/dayjs'

import type { ReplayObservationApi } from '../generated/api.schemas'
import { citedTextToPlainText, parseCitedSegments } from './citations'

export function readModelOutput(obs: ReplayObservationApi): Record<string, unknown> | null {
    const out = obs.scanner_result?.model_output
    return out && typeof out === 'object' ? (out as Record<string, unknown>) : null
}

export function readScore(obs: ReplayObservationApi): number | null {
    const raw = readModelOutput(obs)?.score
    return typeof raw === 'number' ? raw : null
}

export function readConfidence(obs: ReplayObservationApi): number | null {
    const raw = readModelOutput(obs)?.confidence
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

export function readCitedTimestampsMs(obs: ReplayObservationApi): number[] {
    const output = readModelOutput(obs)
    if (!output || obs.status !== 'succeeded') {
        return []
    }
    const [text, segments] =
        obs.scanner_snapshot?.scanner_type === 'summarizer'
            ? [output.summary, output.summary_segments]
            : [output.reasoning, output.reasoning_segments]
    if (typeof text !== 'string' || !text) {
        return []
    }
    const timestamps = new Set<number>()
    for (const segment of parseCitedSegments(text, segments)) {
        if (segment.kind === 'chip') {
            timestamps.add(segment.timestamp_ms)
        }
    }
    return [...timestamps].sort((a, b) => a - b)
}

export interface ObservationSeekbarMark {
    timestampMs: number
    scannerNames: string[]
}

/** One mark per cited timestamp; scanner names merged when they cite the same moment. */
export function observationSeekbarMarks(observations: ReplayObservationApi[]): ObservationSeekbarMark[] {
    const namesByTimestamp = new Map<number, Set<string>>()
    for (const obs of observations) {
        const scannerName = obs.scanner_snapshot?.name
        for (const timestampMs of readCitedTimestampsMs(obs)) {
            const names = namesByTimestamp.get(timestampMs) ?? new Set<string>()
            if (scannerName) {
                names.add(scannerName)
            }
            namesByTimestamp.set(timestampMs, names)
        }
    }
    return [...namesByTimestamp.entries()]
        .sort(([a], [b]) => a - b)
        .map(([timestampMs, names]) => ({ timestampMs, scannerNames: [...names] }))
}

/** One succeeded observation as clipboard text: a metadata line, then the result body. */
export function observationClipboardText(obs: ReplayObservationApi): string | null {
    const output = readModelOutput(obs)
    if (!output || obs.status !== 'succeeded') {
        return null
    }
    const headlineParts: string[] = []
    let body: string | null = null
    if (obs.scanner_snapshot?.scanner_type === 'summarizer') {
        const title = typeof output.title === 'string' && output.title ? output.title : null
        const summary = typeof output.summary === 'string' && output.summary ? output.summary : null
        if (title) {
            headlineParts.push(title)
        }
        body = summary ? citedTextToPlainText(summary, output.summary_segments) : null
    } else {
        const verdict = readVerdict(obs)
        if (verdict) {
            headlineParts.push(`Verdict: ${verdict}`)
        }
        const score = readScore(obs)
        if (score !== null) {
            headlineParts.push(`Score: ${score}`)
        }
        const tags = readTags(obs)
        if (tags.length > 0) {
            headlineParts.push(tags.join(', '))
        }
        const reasoning = readReasoning(obs)
        body = reasoning ? citedTextToPlainText(reasoning, output.reasoning_segments) : null
    }
    if (headlineParts.length === 0 && !body) {
        return null
    }
    const meta = `[${dayjs(obs.created_at).format('YYYY-MM-DD')} · ${obs.session_id}]`
    const headline = headlineParts.length > 0 ? `${meta} ${headlineParts.join(' · ')}` : meta
    return [headline, body].filter(Boolean).join('\n')
}
