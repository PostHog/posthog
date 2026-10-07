import { humanizeBytes } from 'lib/utils/numbers'

import type {
    WarehouseSuggestionApi,
    WarehouseSuggestionApiEvidence,
    WarehouseSuggestionMaterializePayloadApi,
} from './generated/api.schemas'

const MIN_SECONDS_WORTH_NAMING = 60
const SPOKEN_UNITS: [string, number][] = [
    ['day', 24 * 60 * 60],
    ['hour', 60 * 60],
    ['minute', 60],
]
const MAX_SPOKEN_UNITS = 2
const SURFACE_LABELS: Record<string, string> = {
    mcp: 'MCP',
    endpoint: 'endpoints',
    max_ai: 'PostHog AI',
    dashboard: 'dashboards',
    insight: 'insights',
    sql_editor: 'SQL editor',
    notebook: 'notebooks',
    api: 'API',
    product_ui: 'other pages',
    warehouse: 'data warehouse',
    unknown: 'other',
}

export function isMaterializePayload(
    payload: WarehouseSuggestionApi['payload']
): payload is WarehouseSuggestionMaterializePayloadApi {
    return 'refresh_interval_seconds' in payload
}

export function readSentence(evidence: WarehouseSuggestionApiEvidence, windowDays: number): string {
    const requests = Number(evidence.human_requests ?? 0)
    const people = Number(evidence.human_users ?? 0)
    return `Read ${requests} ${requests === 1 ? 'time' : 'times'} by ${people} ${people === 1 ? 'person' : 'people'} in the last ${windowDays} days.`
}

export function savingPhrase(payload: WarehouseSuggestionMaterializePayloadApi): string {
    if (payload.saves_seconds_per_month >= MIN_SECONDS_WORTH_NAMING) {
        return `about ${spokenDuration(payload.saves_seconds_per_month, 1)} of query time`
    }
    return `about ${humanizeBytes(payload.saves_bytes_per_month)} of scanning`
}

export function freshnessSentence(payload: WarehouseSuggestionMaterializePayloadApi): string {
    const interval = spokenDuration(payload.refresh_interval_seconds, 1)
    const after = spokenDuration(payload.freshness_after_seconds, MAX_SPOKEN_UNITS)
    return `Refreshes every ${interval}, so data can be up to ${after} old.`
}

export function surfaceBreakdown(evidence: WarehouseSuggestionApiEvidence): string {
    const bySurface = (evidence.requests_by_surface ?? {}) as Record<string, number>
    return Object.entries(bySurface)
        .sort(([, a], [, b]) => b - a)
        .map(([surface, requests]) => `${SURFACE_LABELS[surface] ?? surface} ${requests}`)
        .join(', ')
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
