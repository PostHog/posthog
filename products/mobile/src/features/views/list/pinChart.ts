import { seriesChartPoints } from '@/features/metrics/chartPoints'
import { parseBucketStart } from '@/lib/dates'
import { formatMetricValue } from '@/model/adapters/metric'
import type { InsightSnapshot } from '@/model/views'
import { seriesColor } from '@/ui/chart/palette'
import type { ChartSeries } from '@/ui/chart/types'

const CURRENT_KEY = 'current'

/**
 * The series a Chart pin draws: the insight's first current series, plus its previous period when the response has
 * one, so the tooltip can show the previous value and the change.
 */
export function pinChartSeries(snapshot: InsightSnapshot): ChartSeries[] {
    if (!snapshot.series) {
        return []
    }
    const points = seriesChartPoints(snapshot.series)
    const inProgress = snapshot.inProgressFrom ? parseBucketStart(snapshot.inProgressFrom) : Number.NaN
    const incompleteFrom = Number.isFinite(inProgress) ? points.findIndex((point) => point.at >= inProgress) : -1
    const current: ChartSeries = {
        key: CURRENT_KEY,
        label: snapshot.name,
        color: seriesColor(0),
        points,
        ...(incompleteFrom >= 0 ? { incompleteFrom } : {}),
    }
    const first = snapshot.allSeries.find((series) => series.compare !== 'previous')
    const previous = first
        ? snapshot.allSeries.find((series) => series.compare === 'previous' && series.seriesIndex === first.seriesIndex)
        : undefined
    if (!previous) {
        return [current]
    }
    const previousPoints = seriesChartPoints({ points: previous.points, interval: snapshot.interval })
    // A previous period with another bucket count cannot pair bucket by bucket, so the chart leaves it out.
    if (previousPoints.length !== points.length) {
        return [current]
    }
    return [
        current,
        {
            key: 'previous',
            label: snapshot.name,
            color: seriesColor(0),
            points: previousPoints,
            compareOf: CURRENT_KEY,
        },
    ]
}

export function snapshotFormatter(snapshot: InsightSnapshot): (value: number) => string {
    return (value) => formatMetricValue(value, snapshot.format.valueFormat, snapshot.format.unit)
}

/** Epoch ms of the last good read, for the chart's "Data until 14:32" note. */
export function dataUntil(snapshot: InsightSnapshot): number | undefined {
    const at = snapshot.lastRefreshAt ? Date.parse(snapshot.lastRefreshAt) : Number.NaN
    return Number.isFinite(at) ? at : undefined
}
