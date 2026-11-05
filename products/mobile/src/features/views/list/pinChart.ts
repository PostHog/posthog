import type { InsightSnapshot } from '@/model/views'

/** Epoch ms of the last good read, for the chart's "Data until 14:32" note. */
export function dataUntil(snapshot: InsightSnapshot): number | undefined {
    const at = snapshot.lastRefreshAt ? Date.parse(snapshot.lastRefreshAt) : Number.NaN
    return Number.isFinite(at) ? at : undefined
}
