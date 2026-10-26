import { humanizeBytes } from 'lib/utils/numbers'

import type {
    WarehouseSuggestionApi,
    WarehouseSuggestionRefreshIntervalBasisEnumApi,
    WarehouseSuggestionDeprecatePayloadApi,
    WarehouseSuggestionEvidenceApi,
    WarehouseSuggestionMaterializePayloadApi,
    WarehouseSuggestionUnmaterializePayloadApi,
} from './generated/api.schemas'

const MIN_SECONDS_WORTH_NAMING = 60
const MIN_BYTES_WORTH_NAMING = 1024 ** 3
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
export const COMBINED_SAVING_LABEL = 'saved a month'

export interface SavingAmount {
    amount: string
    label: string
}

export interface SavingHighlight extends SavingAmount {
    bytes?: SavingAmount
}

export interface SurfaceSegment {
    key: string
    label: string
    count: number
}

export interface SavingsSummary {
    views: number
    saving: MonthlySaving
}

export interface MonthlySaving {
    seconds: number
    bytes: number
}

export interface NamedSaving {
    time: string | null
    bytes: string | null
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

export function isUnmaterializePayload(
    payload: WarehouseSuggestionApi['payload']
): payload is WarehouseSuggestionUnmaterializePayloadApi {
    return 'live_seconds_per_month' in payload
}

export function isDeprecatePayload(
    payload: WarehouseSuggestionApi['payload']
): payload is WarehouseSuggestionDeprecatePayloadApi {
    return 'refresh_seconds_per_month' in payload && !isUnmaterializePayload(payload)
}

export function materializeSaving(payload: WarehouseSuggestionMaterializePayloadApi): MonthlySaving {
    return { seconds: payload.saves_seconds_per_month, bytes: payload.saves_bytes_per_month }
}

export function unmaterializeSaving(payload: WarehouseSuggestionUnmaterializePayloadApi): MonthlySaving {
    return {
        seconds: Math.max(0, payload.refresh_seconds_per_month - payload.live_seconds_per_month),
        bytes: Math.max(0, payload.refresh_bytes_per_month - payload.live_bytes_per_month),
    }
}

export function monthlySaving(payload: WarehouseSuggestionApi['payload']): MonthlySaving | null {
    if (isMaterializePayload(payload)) {
        return materializeSaving(payload)
    }
    return isUnmaterializePayload(payload) ? unmaterializeSaving(payload) : null
}

export function savesTime(saving: MonthlySaving): boolean {
    return saving.seconds >= MIN_SECONDS_WORTH_NAMING
}

export function namedSaving(saving: MonthlySaving, maxUnits: number): NamedSaving {
    const time = savesTime(saving) ? spokenDuration(saving.seconds, maxUnits) : null
    const bytes = !time || saving.bytes >= MIN_BYTES_WORTH_NAMING ? humanizeBytes(saving.bytes) : null
    return { time, bytes }
}

export function suggestedScheduleHint(
    basis: WarehouseSuggestionRefreshIntervalBasisEnumApi | null,
    cadence: string
): string {
    switch (basis) {
        case 'source_sync':
            return `Suggested: every ${cadence}. Its sources don't sync more often than that.`
        case 'read_rate':
            return `Suggested: every ${cadence}. People don't read it more often than that.`
        case 'fastest_schedule':
            return `Suggested: every ${cadence}, the most often PostHog refreshes a view.`
        default:
            return `Suggested: every ${cadence}, the shortest schedule that saves more than it costs.`
    }
}

export function shorterScheduleWarning(
    basis: WarehouseSuggestionRefreshIntervalBasisEnumApi | null,
    cadence: string
): string | null {
    switch (basis) {
        case 'source_sync':
            return `Its sources sync every ${cadence} at most, so refreshing more often reads the same data again.`
        case 'read_rate':
            return `People don't read it more often than every ${cadence}, so extra refreshes mostly go unread.`
        case 'fastest_schedule':
            return null
        default:
            return `Refreshing more often than every ${cadence} can cost more than it saves.`
    }
}

export function refreshModeLabel(incremental: boolean, incrementalKey: string | null): string {
    if (!incremental) {
        return 'Each refresh rebuilds the whole table'
    }
    return incrementalKey ? `Each refresh reads only new rows by ${incrementalKey}` : 'Each refresh reads only new rows'
}

export function savingHighlight(saving: MonthlySaving): SavingHighlight {
    const { time, bytes } = namedSaving(saving, 1)
    if (!time) {
        return { amount: `~${bytes}`, label: 'less data scanned a month' }
    }
    return {
        amount: `~${time}`,
        label: 'query time saved a month',
        ...(bytes ? { bytes: { amount: `~${bytes}`, label: 'less scanned' } } : {}),
    }
}

export function savingSentence(saving: MonthlySaving): string {
    const { time, bytes } = namedSaving(saving, 1)
    const parts = [time && `${time} of query time`, bytes && `${bytes} of scanning`].filter(Boolean)
    return `Saves about ${parts.join(' and ')} a month`
}

export function monthlyCost(cost: MonthlySaving): string {
    const { time, bytes } = namedSaving(cost, MAX_SPOKEN_UNITS)
    if (!time) {
        return `about ${bytes} scanned a month`
    }
    return bytes ? `about ${time} a month, scanning ${bytes}` : `about ${time} a month`
}

export function readTimeLabel(seconds: number): string {
    if (seconds >= MIN_SECONDS_WORTH_NAMING) {
        return `Each read takes about ${spokenDuration(seconds, MAX_SPOKEN_UNITS)}`
    }
    const wholeSeconds = Math.max(1, Math.round(seconds))
    return `Each read takes about ${countOf(wholeSeconds, 'second', 'seconds')}`
}

const NOT_NOW_CONDITIONS: Record<string, string> = {
    certify: 'Suggested again if reads grow a lot.',
    deprecate: 'Suggested again if its refreshes cost a lot more.',
    materialize: 'Suggested again if it would save a lot more.',
    unmaterialize: 'Suggested again if it would save a lot more.',
}

export function notNowCondition(kind: string): string {
    return NOT_NOW_CONDITIONS[kind] ?? 'Suggested again if the case for it grows a lot.'
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

export function refreshCostLabel(
    payload: Pick<WarehouseSuggestionDeprecatePayloadApi, 'refresh_seconds_per_month' | 'refresh_bytes_per_month'>
): string {
    const { time, bytes } = namedSaving(
        { seconds: payload.refresh_seconds_per_month, bytes: payload.refresh_bytes_per_month },
        MAX_SPOKEN_UNITS
    )
    if (!time) {
        return `Refreshes scan about ${bytes} a month`
    }
    return bytes ? `Refreshes use about ${time} a month and scan ${bytes}` : `Refreshes use about ${time} a month`
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

export function countOf(count: number, singular: string, plural: string): string {
    return `${count} ${count === 1 ? singular : plural}`
}
