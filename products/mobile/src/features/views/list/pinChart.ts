import type { InsightSnapshot } from '@/model/views'
import type { ChartSeries } from '@/ui/chart/types'

import { snapshotChartSeries } from '../snapshotChart'

/**
 * The series a Chart pin draws: the insight's first current series, plus its previous period when the response has
 * one, so the tooltip can show the previous value and the change. The pin has no legend, so it draws only the series
 * its big value describes.
 */
export function pinChartSeries(snapshot: InsightSnapshot): ChartSeries[] {
    const series = snapshotChartSeries(snapshot)
    const first = series.find((candidate) => candidate.compareOf === undefined)
    return first ? series.filter((candidate) => candidate === first || candidate.compareOf === first.key) : []
}

/** Epoch ms of the last good read, for the chart's "Data until 14:32" note. */
export function dataUntil(snapshot: InsightSnapshot): number | undefined {
    const at = snapshot.lastRefreshAt ? Date.parse(snapshot.lastRefreshAt) : Number.NaN
    return Number.isFinite(at) ? at : undefined
}
