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

/** The dock shows summaries only; observations from the team's own scanners live in the sidebar tab. */
export function isSummaryObservation(obs: ReplayObservationApi): boolean {
    return obs.scanner_snapshot?.scanner_type === 'summarizer'
}

/** Summarizer output: the one-line headline. */
export function readTitle(obs: ReplayObservationApi): string | null {
    const raw = readModelOutput(obs)?.title
    return typeof raw === 'string' && raw ? raw : null
}

/** Summarizer output: the narrative body. */
export function readSummary(obs: ReplayObservationApi): string | null {
    const raw = readModelOutput(obs)?.summary
    return typeof raw === 'string' && raw ? raw : null
}

/** `error_reason` is stored as `kind:message`; the message is the half worth showing a person. */
export function readErrorMessage(obs: ReplayObservationApi): string | null {
    if (!obs.error_reason) {
        return null
    }
    const separator = obs.error_reason.indexOf(':')
    return separator === -1 ? obs.error_reason : obs.error_reason.slice(separator + 1)
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

export interface ObservationSeekbarMarkEntry {
    scannerName: string | null
    headline: string | null
    snippet: string | null
}

export interface ObservationSeekbarMark {
    timestampMs: number
    entries: ObservationSeekbarMarkEntry[]
}

const SNIPPET_MAX_LENGTH = 160

function lastSentence(text: string): string | null {
    const trimmed = text.trim()
    if (!trimmed) {
        return null
    }
    // No lookbehind regex, it breaks chunk parsing on older browsers.
    let start = 0
    for (const match of trimmed.matchAll(/[.!?]+\s+/g)) {
        start = match.index + match[0].length
    }
    const last = trimmed
        .slice(start)
        .replace(/[.!?]+$/, '')
        .trim()
    if (!last) {
        return null
    }
    return last.length > SNIPPET_MAX_LENGTH ? `${last.slice(0, SNIPPET_MAX_LENGTH - 1)}…` : last
}

/** Cited timestamps in a succeeded observation's output, each with the sentence that cites it. */
function readCitations(obs: ReplayObservationApi): { timestampMs: number; snippet: string | null }[] {
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
    const parsed = parseCitedSegments(text, segments)
    const snippetByTimestamp = new Map<number, string | null>()
    parsed.forEach((segment, index) => {
        if (segment.kind !== 'chip' || snippetByTimestamp.has(segment.timestamp_ms)) {
            return
        }
        let snippet: string | null = null
        for (let i = index - 1; i >= 0; i--) {
            const previous = parsed[i]
            if (previous.kind === 'text') {
                snippet = lastSentence(previous.value)
                break
            }
        }
        snippetByTimestamp.set(segment.timestamp_ms, snippet)
    })
    return [...snippetByTimestamp.entries()].map(([timestampMs, snippet]) => ({ timestampMs, snippet }))
}

function observationHeadline(obs: ReplayObservationApi): string | null {
    const scannerType = obs.scanner_snapshot?.scanner_type
    if (scannerType === 'monitor') {
        const verdict = readVerdict(obs)
        return verdict ? `Verdict: ${verdict}` : null
    }
    if (scannerType === 'scorer') {
        const score = readScore(obs)
        return score !== null ? `Score: ${score}` : null
    }
    return null
}

/** One mark per cited timestamp; entries merged when scanners cite the same moment. */
export function observationSeekbarMarks(observations: ReplayObservationApi[]): ObservationSeekbarMark[] {
    const entriesByTimestamp = new Map<number, Map<string, ObservationSeekbarMarkEntry>>()
    for (const obs of observations) {
        const scannerName = obs.scanner_snapshot?.name ?? null
        const headline = observationHeadline(obs)
        for (const { timestampMs, snippet } of readCitations(obs)) {
            const entries = entriesByTimestamp.get(timestampMs) ?? new Map<string, ObservationSeekbarMarkEntry>()
            entries.set(JSON.stringify([scannerName, headline, snippet]), { scannerName, headline, snippet })
            entriesByTimestamp.set(timestampMs, entries)
        }
    }
    return [...entriesByTimestamp.entries()]
        .sort(([a], [b]) => a - b)
        .map(([timestampMs, entries]) => ({ timestampMs, entries: [...entries.values()] }))
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
