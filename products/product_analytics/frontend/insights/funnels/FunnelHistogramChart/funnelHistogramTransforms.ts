import type { Series } from 'lib/hog-charts'
import { humanFriendlyDuration } from 'lib/utils'

import type { HistogramGraphDatum } from '~/types'

export const FUNNEL_HISTOGRAM_SERIES_KEY = 'funnel-histogram-conversions'
export const FUNNEL_HISTOGRAM_SERIES_LABEL = 'Conversions'

export interface FunnelHistogramData {
    /** Single bar series; `data[i]` is the conversion count for bin `i`. */
    series: Series[]
    /** Category labels — the lower bound of each duration bin, one per bar. */
    labels: string[]
    /** Per-bar percentage label (share of total conversions), indexed to match `labels`. */
    barLabels: string[]
}

/** Maps the funnel time-to-convert bins onto a categorical hog-charts bar series. */
export function buildFunnelHistogramData(
    histogramGraphData: HistogramGraphDatum[],
    options?: { color?: string }
): FunnelHistogramData {
    return {
        labels: histogramGraphData.map((datum) => humanFriendlyDuration(datum.bin0, { maxUnits: 2 })),
        barLabels: histogramGraphData.map((datum) => datum.label),
        series: [
            {
                key: FUNNEL_HISTOGRAM_SERIES_KEY,
                label: FUNNEL_HISTOGRAM_SERIES_LABEL,
                data: histogramGraphData.map((datum) => datum.count),
                color: options?.color,
            },
        ],
    }
}
