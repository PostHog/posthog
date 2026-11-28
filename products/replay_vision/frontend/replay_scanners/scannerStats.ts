import type { ObservationStatsApi } from '../generated/api.schemas'

export interface ObservationStatusStats {
    total: number
    succeeded: number
    failed: number
    ineligible: number
    inFlight: number
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

export function availableTagsFromStats(stats: ObservationStatsApi | null): string[] {
    return stats?.available_tags ?? []
}
