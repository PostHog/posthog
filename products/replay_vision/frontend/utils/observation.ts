import { dayjs } from 'lib/dayjs'
import { colonDelimitedDuration } from 'lib/utils/durations'

import { type ReplayObservationApi, ScannerOriginEnumApi, ScannerTypeEnumApi } from '../generated/api.schemas'
import { citedTextToPlainText, parseCitedSegments } from './citations'
import { flattenMarkdownToLine } from './markdown'

/** The dock's built-in prompt and the observations it produces have to answer to one name. */
export const BUILT_IN_SUMMARY_LABEL = 'Quick summary'

/** Only a confirmed saved scanner has a page, so an origin a later release adds fails safe to no link. */
export function hasScannerPage(obs: Pick<ReplayObservationApi, 'scanner_origin'>): boolean {
    return obs.scanner_origin === ScannerOriginEnumApi.Configured
}

/** What to call the scan behind an observation, anywhere one is named next to its result. */
export function scannerLabel(obs: Pick<ReplayObservationApi, 'scanner_origin' | 'scanner_snapshot'>): string {
    if (obs.scanner_origin !== ScannerOriginEnumApi.Inline) {
        return obs.scanner_snapshot?.name || 'Scanner'
    }
    // A one-off scan has no name to borrow, so its result answers to whatever the dock called the prompt.
    return obs.scanner_snapshot?.scanner_type === ScannerTypeEnumApi.Summarizer
        ? BUILT_IN_SUMMARY_LABEL
        : 'One-off scan'
}

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

/** Summarizer output, which is the dock's primary content. */
export function isSummaryObservation(obs: ReplayObservationApi): boolean {
    return obs.scanner_snapshot?.scanner_type === 'summarizer'
}

/** A scan that settled without a result: the scanner failed, or the recording did not qualify. */
export function isUnsuccessfulScan(obs: ReplayObservationApi): boolean {
    return obs.status === 'failed' || obs.status === 'ineligible'
}

/**
 * What the dock shows below the player: every summary, plus any other scanner that left no result.
 *
 * A succeeded scanner observation stays in the sidebar tab, which is where the team reads its own
 * scanners. One that failed or was ineligible is different: nothing below the player would otherwise
 * say why no result arrived, so the run is only discoverable by opening the sidebar and looking.
 */
export function dockObservations(observations: ReplayObservationApi[]): ReplayObservationApi[] {
    // A summarizer that failed is already carried by the first filter, so the second skips summaries
    // rather than listing them twice.
    return [
        ...observations.filter(isSummaryObservation),
        ...observations.filter((obs) => !isSummaryObservation(obs) && isUnsuccessfulScan(obs)),
    ]
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
    scannerName: string
    headline: string | null
    snippet: string | null
    sentence: string | null
}

export interface ObservationSeekbarMark {
    timestampMs: number
    entries: ObservationSeekbarMarkEntry[]
    /** A monitor answered yes here, so the moment is drawn stronger. */
    flagged: boolean
}

export function isFlaggedObservation(obs: ReplayObservationApi): boolean {
    return obs.scanner_snapshot?.scanner_type === 'monitor' && readVerdict(obs) === 'yes'
}

/** Models cite whole seconds, so a sub-second offset is the same moment. */
export function markBucketMs(timestampMs: number): number {
    return Math.floor(Math.max(0, timestampMs) / 1000) * 1000
}

const SNIPPET_MAX_LENGTH = 160
const SNIPPET_MIN_WORDS = 2
const CHIP_PLACEHOLDER = '\uE000'
const CHIP_PLACEHOLDER_RE = /\uE000/g
const DANGLING_TAIL_RE =
    /\s+(a|an|the|and|or|but|as|at|in|on|to|of|for|by|with|from|into|onto|about|around|near|after|before|during|until|when|while|where|which|that|then|so)$/i

/** Fragments left between chips, e.g. `) and the banner appeared` or `, then it failed (see`. */
function tidyClause(fragment: string): string {
    let clause = fragment
        .replace(/[.!?]+\s*$/, '')
        .replace(/^[^\p{L}\p{N}"'“‘([]+/u, '')
        .replace(/^(and|but|then|so)\b\s*/i, '')
        .replace(/\s*\([^)]*$/, '')
    for (;;) {
        const trimmed = clause.replace(/[\s,;:\-–—]+$/, '').replace(DANGLING_TAIL_RE, '')
        if (trimmed === clause) {
            return clause
        }
        clause = trimmed
    }
}

function wordCount(text: string): number {
    return text.split(/\s+/).filter(Boolean).length
}

function tidySentence(text: string): string {
    return text
        .replace(/\s+([,.;:!?)])/g, '$1')
        .replace(/\s{2,}/g, ' ')
        .trim()
}

function truncate(text: string): string {
    return text.length > SNIPPET_MAX_LENGTH ? `${text.slice(0, SNIPPET_MAX_LENGTH - 1)}…` : text
}

interface Citation {
    timestampMs: number
    snippet: string | null
    sentence: string | null
}

/** Cited timestamps in a succeeded observation's output, each with the clause that cites it. */
function readCitations(obs: ReplayObservationApi): Citation[] {
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
    let flat = ''
    const chips: { timestampMs: number; offset: number }[] = []
    for (const segment of parseCitedSegments(text, segments)) {
        if (segment.kind === 'chip') {
            flat += flat ? ` ${CHIP_PLACEHOLDER}` : CHIP_PLACEHOLDER
            chips.push({ timestampMs: segment.timestamp_ms, offset: flat.length - 1 })
            continue
        }
        const piece = flattenMarkdownToLine(segment.value)
        if (piece) {
            flat += flat ? ` ${piece}` : piece
        }
    }
    // No lookbehind regex, it breaks chunk parsing on older browsers.
    const sentenceStarts = [0, ...[...flat.matchAll(/[.!?]+\s+/g)].map((m) => m.index + m[0].length)]
    const sentenceStart = (offset: number): number => {
        let start = 0
        for (const s of sentenceStarts) {
            if (s > offset) {
                break
            }
            start = s
        }
        return start
    }
    const hasText = (slice: string): boolean => slice.replace(CHIP_PLACEHOLDER_RE, '').trim() !== ''

    const seen = new Set<number>()
    const citations: Citation[] = []
    for (const chip of chips) {
        if (seen.has(chip.timestampMs)) {
            continue
        }
        seen.add(chip.timestampMs)
        let sStart = sentenceStart(chip.offset)
        let sEnd = sentenceStarts.find((s) => s > chip.offset) ?? flat.length
        if (sStart > 0 && !hasText(flat.slice(sStart, chip.offset))) {
            sEnd = sStart
            sStart = sentenceStart(sStart - 1)
        }
        const inSentence = chips.filter((c) => c.offset >= sStart && c.offset < sEnd)
        const previous = inSentence.filter((c) => c.offset < chip.offset).pop()
        const next = inSentence.find((c) => c.offset > chip.offset)
        const from = previous ? previous.offset + 1 : sStart
        const to = next ? next.offset : sEnd
        let clause = tidyClause(flat.slice(from, Math.min(chip.offset, sEnd)))
        if (wordCount(clause) < SNIPPET_MIN_WORDS) {
            clause = tidyClause(tidySentence(flat.slice(from, to).replace(CHIP_PLACEHOLDER_RE, '')))
        }
        let midSentence = hasText(flat.slice(sStart, from))
        if (wordCount(clause) < SNIPPET_MIN_WORDS) {
            clause = tidyClause(tidySentence(flat.slice(sStart, sEnd).replace(CHIP_PLACEHOLDER_RE, '')))
            midSentence = false
        }
        const times = inSentence.map((c) => c.timestampMs)
        const raw = flat.slice(sStart, sEnd)
        const sentence = hasText(raw)
            ? tidySentence(
                  raw.replace(
                      CHIP_PLACEHOLDER_RE,
                      () => `(${colonDelimitedDuration(Math.floor(times.shift()! / 1000), null)})`
                  )
              ).replace(/[\s.!?,;:]+$/, '')
            : null
        citations.push({
            timestampMs: chip.timestampMs,
            snippet: clause
                ? truncate(midSentence ? `…${clause}` : clause.charAt(0).toUpperCase() + clause.slice(1))
                : null,
            sentence,
        })
    }
    return citations
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

/** One mark per cited second; entries merged when scanners cite the same moment. */
export function observationSeekbarMarks(observations: ReplayObservationApi[]): ObservationSeekbarMark[] {
    const entriesByTimestamp = new Map<number, Map<string, ObservationSeekbarMarkEntry>>()
    const flaggedTimestamps = new Set<number>()
    for (const obs of observations) {
        const scannerName = scannerLabel(obs)
        const headline = observationHeadline(obs)
        const flagged = isFlaggedObservation(obs)
        for (const { timestampMs, snippet, sentence } of readCitations(obs)) {
            const bucket = markBucketMs(timestampMs)
            const entries = entriesByTimestamp.get(bucket) ?? new Map<string, ObservationSeekbarMarkEntry>()
            entries.set(JSON.stringify([scannerName, headline, snippet]), { scannerName, headline, snippet, sentence })
            entriesByTimestamp.set(bucket, entries)
            if (flagged) {
                flaggedTimestamps.add(bucket)
            }
        }
    }
    return [...entriesByTimestamp.entries()]
        .sort(([a], [b]) => a - b)
        .map(([timestampMs, entries]) => ({
            timestampMs,
            entries: [...entries.values()],
            flagged: flaggedTimestamps.has(timestampMs),
        }))
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
