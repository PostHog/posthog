// Pure derivations of the scanner "overview" stat shapes from the observations-stats endpoint
// (ObservationStatsApi). Shared by replayScannerLogic (Observations tab: metric strip + tag options)
// and scannerOverviewLogic (Overview tab: verdict mix / tag rankings / score distribution / coverage),
// so the two tabs compute identical shapes from the same endpoint without duplicating the mapping.

import { dayjs } from 'lib/dayjs'
import { dateStringToDayJs } from 'lib/utils/dateFilters'

import type { ObservationStatsApi } from '../generated/api.schemas'

export interface ObservationStatusStats {
    total: number
    succeeded: number
    failed: number
    ineligible: number
    inFlight: number
}

export interface MonitorStats {
    yesTotal: number
    noTotal: number
    inconclusiveTotal: number
}

export interface ClassifierTagStats {
    fixedRanked: [string, number][]
    freeformRanked: [string, number][]
    // Person-backed users per tag — the number a "save as cohort" would actually add — keyed by tag.
    // A tag maps to `undefined` when the backend couldn't resolve persons, so callers leave the save
    // button enabled rather than block a save they can't prove would fail.
    fixedTagUsers: Record<string, number | undefined>
    freeformTagUsers: Record<string, number | undefined>
    totalWithTags: number
}

export interface ScorerSummary {
    min: number
    p25: number
    median: number
    mean: number
    p75: number
    max: number
    count: number
}

export interface ScorerHistogram {
    labels: string[]
    counts: number[]
}

export interface CoverageStats {
    recentSessions: number
    totalSessions: number
    recentDays: number
}

export function deriveObservationStatusStats(stats: ObservationStatsApi | null): ObservationStatusStats {
    if (!stats) {
        return { total: 0, succeeded: 0, failed: 0, ineligible: 0, inFlight: 0 }
    }
    const c = stats.status_counts
    return {
        total: c.total,
        succeeded: c.succeeded,
        failed: c.failed,
        ineligible: c.ineligible,
        inFlight: c.in_flight,
    }
}

export function deriveMonitorStats(stats: ObservationStatsApi | null): MonitorStats {
    return {
        yesTotal: stats?.monitor?.yes_total ?? 0,
        noTotal: stats?.monitor?.no_total ?? 0,
        inconclusiveTotal: stats?.monitor?.inconclusive_total ?? 0,
    }
}

// The stats endpoint carries a per-tag person-backed `users` count. The generated type can lag a
// regeneration, so read it through this widened shape rather than handwriting a fresh API type.
type RankedTagWithUsers = { tag: string; count: number; users?: number }

function tagUsersMap(entries: RankedTagWithUsers[]): Record<string, number | undefined> {
    const map: Record<string, number | undefined> = {}
    for (const entry of entries) {
        map[entry.tag] = entry.users
    }
    return map
}

export function deriveClassifierTagStats(stats: ObservationStatsApi | null): ClassifierTagStats {
    const fixed = (stats?.classifier?.fixed_ranked ?? []) as RankedTagWithUsers[]
    const freeform = (stats?.classifier?.freeform_ranked ?? []) as RankedTagWithUsers[]
    return {
        fixedRanked: fixed.map((t) => [t.tag, t.count] as [string, number]),
        freeformRanked: freeform.map((t) => [t.tag, t.count] as [string, number]),
        fixedTagUsers: tagUsersMap(fixed),
        freeformTagUsers: tagUsersMap(freeform),
        totalWithTags: stats?.classifier?.total_with_tags ?? 0,
    }
}

export function deriveScorerSummary(stats: ObservationStatsApi | null): ScorerSummary | null {
    return stats?.scorer?.summary ?? null
}

export function deriveScorerHistogram(stats: ObservationStatsApi | null): ScorerHistogram | null {
    return stats?.scorer?.histogram ?? null
}

export function deriveCoverageStats(stats: ObservationStatsApi | null): CoverageStats {
    return {
        recentSessions: stats?.coverage.recent_sessions ?? 0,
        totalSessions: stats?.coverage.total_sessions ?? 0,
        recentDays: stats?.coverage.recent_days ?? 14,
    }
}

export function availableTagsFromStats(stats: ObservationStatsApi | null): string[] {
    return stats?.available_tags ?? []
}

// The stats endpoint's `recent_days` (its coverage/"last N days" window) is derived from a date range —
// used by the chart's coverage strip. 'all' has no anchor, so a year is the practical ceiling.
export function daysFromDateRange(dateFrom: string | null, dateTo: string | null): number {
    if (!dateFrom) {
        return 14
    }
    const from = dateFrom === 'all' ? dayjs().subtract(1, 'year') : dateStringToDayJs(dateFrom)
    if (!from) {
        return 14
    }
    const to = (dateTo && dateTo !== 'all' ? dateStringToDayJs(dateTo) : null) ?? dayjs()
    return Math.max(1, to.diff(from, 'day'))
}

export interface SummarizerFacetStats {
    frictionRanked: [string, number][]
    keywordRanked: [string, number][]
    totalSucceeded: number
    totalWithFriction: number
}

export function deriveSummarizerFacetStats(stats: ObservationStatsApi | null): SummarizerFacetStats {
    return {
        frictionRanked: (stats?.summarizer?.friction_ranked ?? []).map((f) => [f.term, f.count] as [string, number]),
        keywordRanked: (stats?.summarizer?.keyword_ranked ?? []).map((f) => [f.term, f.count] as [string, number]),
        // Summaries that report no friction still count toward the friction rate, so the denominator
        // is every succeeded summary rather than only those that emitted facets.
        totalSucceeded: stats?.status_counts.succeeded ?? 0,
        totalWithFriction: stats?.summarizer?.total_with_friction ?? 0,
    }
}
