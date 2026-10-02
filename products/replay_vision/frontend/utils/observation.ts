import { dayjs } from 'lib/dayjs'

import { type ReplayObservationApi, ScannerOriginEnumApi, ScannerTypeEnumApi } from '../generated/api.schemas'
import { citedTextToPlainText } from './citations'

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

export type ConfidenceLevel = { type: 'success' | 'warning' | 'danger'; label: 'High' | 'Medium' | 'Low' }

export function confidenceLevel(value: number): ConfidenceLevel {
    return value >= 0.8
        ? { type: 'success', label: 'High' }
        : value >= 0.5
          ? { type: 'warning', label: 'Medium' }
          : { type: 'danger', label: 'Low' }
}

export type MonitorVerdict = 'yes' | 'no' | 'inconclusive'

export const VERDICT_LABEL: Record<MonitorVerdict, string> = { yes: 'Yes', no: 'No', inconclusive: 'Inconclusive' }

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

export function isFlaggedObservation(obs: ReplayObservationApi): boolean {
    return obs.scanner_snapshot?.scanner_type === 'monitor' && readVerdict(obs) === 'yes'
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
