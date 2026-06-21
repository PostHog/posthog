import type { Series } from '@posthog/quill-charts'

import { humanFriendlyDuration } from 'lib/utils/durations'

import type { HistogramGraphDatum } from '~/types'

export const FUNNEL_HISTOGRAM_SERIES_KEY = 'funnel-histogram-conversions'
export const FUNNEL_HISTOGRAM_SERIES_LABEL = 'Conversions'
/** When comparing, the current period is relabelled to disambiguate it from the previous one. */
export const FUNNEL_HISTOGRAM_CURRENT_SERIES_LABEL = 'Current'
export const FUNNEL_HISTOGRAM_PREVIOUS_SERIES_KEY = 'funnel-histogram-conversions-previous'
export const FUNNEL_HISTOGRAM_PREVIOUS_SERIES_LABEL = 'Previous'

export interface FunnelHistogramData {
    /** One bar series per period; `data[i]` is the conversion count for bin `i`. */
    series: Series[]
    /** Category labels — the lower bound of each duration bin, one per bar. */
    labels: string[]
    /** Per-bar percentage label (share of total conversions), indexed to match `labels`. */
    barLabels: string[]
}

/** Maps the funnel time-to-convert bins onto categorical hog-charts bar series.
 *
 * When `options.previous` is provided (compare-to-previous), a second desaturated series is
 * emitted. Both periods share the current period's bin boundaries, so the previous series is
 * indexed positionally against the same `labels`. */
export function buildFunnelHistogramData(
    histogramGraphData: HistogramGraphDatum[],
    options?: { color?: string; previous?: { data: HistogramGraphDatum[]; color?: string } }
): FunnelHistogramData {
    const series: Series[] = [
        {
            key: FUNNEL_HISTOGRAM_SERIES_KEY,
            label: options?.previous ? FUNNEL_HISTOGRAM_CURRENT_SERIES_LABEL : FUNNEL_HISTOGRAM_SERIES_LABEL,
            data: histogramGraphData.map((datum) => datum.count),
            color: options?.color,
        },
    ]

    if (options?.previous) {
        series.push({
            key: FUNNEL_HISTOGRAM_PREVIOUS_SERIES_KEY,
            label: FUNNEL_HISTOGRAM_PREVIOUS_SERIES_LABEL,
            data: options.previous.data.map((datum) => datum.count),
            color: options.previous.color,
        })
    }

    return {
        labels: histogramGraphData.map((datum) => humanFriendlyDuration(datum.bin0, { maxUnits: 2 })),
        barLabels: histogramGraphData.map((datum) => datum.label),
        series,
    }
}
