import { humanizeBytes } from 'lib/utils/numbers'
import { CADENCE_LABELS } from 'scenes/data-warehouse/saved_queries/SyncFrequencySelect'

import type {
    WarehouseSuggestionApi,
    WarehouseSuggestionDeprecatePayloadApi,
    WarehouseSuggestionEvidenceApi,
    WarehouseSuggestionMaterializePayloadApi,
} from './generated/api.schemas'
import { intervalForSeconds } from './refreshIntervals'

const MIN_SECONDS_WORTH_NAMING = 60
const SPOKEN_UNITS: [string, number][] = [
    ['day', 24 * 60 * 60],
    ['hour', 60 * 60],
    ['minute', 60],
]
const MAX_SPOKEN_UNITS = 2
const SURFACE_LABELS: Record<string, string> = {
    mcp: 'MCP',
    posthog_ai: 'PostHog AI',
    desktop: 'Desktop app',
    endpoints: 'Endpoints',
    dashboard: 'Dashboards',
    insight: 'Insights',
    sql_editor: 'SQL editor',
    notebook: 'Notebooks',
    api: 'API',
    app: 'Other pages',
    unknown: 'Other',
}
export const UNKNOWN_SOURCES_CAVEAT = 'Some sources have no sync schedule, so their age is unknown.'
export const QUERY_LOG_CAVEAT = 'Counts come from the query log. Cached dashboard views are not counted.'

export interface SavingHighlight {
    amount: string
    label: string
}

export interface SurfaceSegment {
    key: string
    label: string
    count: number
}

export interface SavingsSummary {
    timeViews: number
    savedSeconds: number
    bytesViews: number
    savedBytes: number
}

export interface DataAgeLabel {
    label: string
    caveat: string | null
}

export function isMaterializePayload(
    payload: WarehouseSuggestionApi['payload']
): payload is WarehouseSuggestionMaterializePayloadApi {
    return 'refresh_interval_seconds' in payload
}

export function isDeprecatePayload(
    payload: WarehouseSuggestionApi['payload']
): payload is WarehouseSuggestionDeprecatePayloadApi {
    return 'refresh_seconds_per_month' in payload
}

export function savesTime(payload: WarehouseSuggestionMaterializePayloadApi): boolean {
    return payload.saves_seconds_per_month >= MIN_SECONDS_WORTH_NAMING
}

export function savingHighlight(payload: WarehouseSuggestionMaterializePayloadApi): SavingHighlight {
    if (savesTime(payload)) {
        return { amount: `~${spokenDuration(payload.saves_seconds_per_month, 1)}`, label: 'query time saved a month' }
    }
    return { amount: `~${humanizeBytes(payload.saves_bytes_per_month)}`, label: 'less data scanned a month' }
}

export function savingSentence(payload: WarehouseSuggestionMaterializePayloadApi): string {
    if (savesTime(payload)) {
        return `Saves about ${spokenDuration(payload.saves_seconds_per_month, 1)} of query time a month`
    }
    return `Saves about ${humanizeBytes(payload.saves_bytes_per_month)} of scanning a month`
}

export function savingsSummaryText(summary: SavingsSummary): string {
    const timePart =
        summary.timeViews > 0
            ? `${countOf(summary.timeViews, 'view', 'views')} could save about ${spokenDuration(summary.savedSeconds, 1)} of query time a month`
            : null
    if (timePart && summary.bytesViews > 0) {
        return `${timePart}, and ${humanizeBytes(summary.savedBytes)} less scanning`
    }
    if (timePart) {
        return timePart
    }
    if (summary.bytesViews > 0) {
        return `${countOf(summary.bytesViews, 'view', 'views')} could save ${humanizeBytes(summary.savedBytes)} of scanning a month`
    }
    return ''
}

export function certificationSummaryText(suggestions: WarehouseSuggestionApi[]): string {
    const certify = suggestions.filter((suggestion) => suggestion.kind === 'certify').length
    const deprecate = suggestions.filter((suggestion) => suggestion.kind === 'deprecate').length
    return [certify > 0 ? `${certify} to certify` : null, deprecate > 0 ? `${deprecate} to mark deprecated` : null]
        .filter(Boolean)
        .join(' · ')
}

export function readSummary(evidence: WarehouseSuggestionEvidenceApi): string {
    return `${countOf(evidence.human_requests ?? 0, 'read', 'reads')} · ${countOf(evidence.human_users ?? 0, 'person', 'people')}`
}

export function daysReadLabel(evidence: WarehouseSuggestionEvidenceApi, windowDays: number): string {
    return `Read on ${evidence.human_days ?? 0} of the last ${windowDays} days`
}

export function noReadsLabel(windowDays: number): string {
    return `No reads recorded in ${windowDays} days`
}

export function refreshCostLabel(payload: WarehouseSuggestionDeprecatePayloadApi): string {
    if (payload.refresh_seconds_per_month >= MIN_SECONDS_WORTH_NAMING) {
        return `Refreshes use about ${spokenDuration(payload.refresh_seconds_per_month, MAX_SPOKEN_UNITS)} a month`
    }
    return `Refreshes scan about ${humanizeBytes(payload.refresh_bytes_per_month)} a month`
}

export function refreshLabel(intervalSeconds: number): string {
    const interval = intervalForSeconds(intervalSeconds)
    return `Refreshes every ${interval ? CADENCE_LABELS[interval] : spokenDuration(intervalSeconds, 1)}`
}

function dataAgeAfterSeconds(payload: WarehouseSuggestionMaterializePayloadApi, intervalSeconds: number): number {
    return intervalSeconds + (payload.freshness_today_seconds ?? 0)
}

export function hasUnknownSources(payload: WarehouseSuggestionMaterializePayloadApi): boolean {
    return payload.unknown_sources.names.length + payload.unknown_sources.hidden_count > 0
}

export function dataAgeLabel(payload: WarehouseSuggestionMaterializePayloadApi, intervalSeconds: number): DataAgeLabel {
    if (hasUnknownSources(payload)) {
        return {
            label: `Adds up to ${spokenDuration(intervalSeconds, MAX_SPOKEN_UNITS)} to source age`,
            caveat: UNKNOWN_SOURCES_CAVEAT,
        }
    }
    const age = spokenDuration(dataAgeAfterSeconds(payload, intervalSeconds), MAX_SPOKEN_UNITS)
    return { label: `Data up to ${age} old`, caveat: null }
}

export function todayAgeLabel(payload: WarehouseSuggestionMaterializePayloadApi): string {
    if (hasUnknownSources(payload)) {
        return 'Today: unknown for some sources'
    }
    if (payload.freshness_today_seconds === null) {
        return 'Today: live'
    }
    return `Today: up to ${spokenDuration(payload.freshness_today_seconds, MAX_SPOKEN_UNITS)} old`
}

export function surfaceSegments(evidence: WarehouseSuggestionEvidenceApi): SurfaceSegment[] {
    return Object.entries(evidence.requests_by_surface ?? {})
        .sort(([, a], [, b]) => b - a)
        .map(([key, count]) => ({ key, label: SURFACE_LABELS[key] ?? key, count }))
}

export function spokenDuration(seconds: number, maxUnits: number): string {
    const parts: string[] = []
    let remaining = Math.round(seconds)
    for (const [unit, unitSeconds] of SPOKEN_UNITS) {
        const count = Math.floor(remaining / unitSeconds)
        if (count > 0 && parts.length < maxUnits) {
            parts.push(`${count} ${unit}${count === 1 ? '' : 's'}`)
            remaining -= count * unitSeconds
        }
    }
    return parts.length > 0 ? parts.join(' and ') : 'under a minute'
}

function countOf(count: number, singular: string, plural: string): string {
    return `${count} ${count === 1 ? singular : plural}`
}
