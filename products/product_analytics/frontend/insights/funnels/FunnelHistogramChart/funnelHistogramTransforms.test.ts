import type { HistogramGraphDatum } from '~/types'

import {
    buildFunnelHistogramData,
    FUNNEL_HISTOGRAM_CURRENT_SERIES_LABEL,
    FUNNEL_HISTOGRAM_PREVIOUS_SERIES_KEY,
    FUNNEL_HISTOGRAM_PREVIOUS_SERIES_LABEL,
    FUNNEL_HISTOGRAM_SERIES_KEY,
    FUNNEL_HISTOGRAM_SERIES_LABEL,
} from './funnelHistogramTransforms'

const bins: HistogramGraphDatum[] = [
    { id: 0, bin0: 0, bin1: 60, count: 12, label: '60%' },
    { id: 60, bin0: 60, bin1: 120, count: 6, label: '30%' },
    { id: 120, bin0: 120, bin1: 180, count: 2, label: '10%' },
]

const previousBins: HistogramGraphDatum[] = [
    { id: 0, bin0: 0, bin1: 60, count: 4, label: '40%' },
    { id: 60, bin0: 60, bin1: 120, count: 5, label: '50%' },
    { id: 120, bin0: 120, bin1: 180, count: 1, label: '10%' },
]

describe('buildFunnelHistogramData', () => {
    it('maps the bins onto a single conversion bar series', () => {
        const { series } = buildFunnelHistogramData(bins)

        expect(series).toHaveLength(1)
        expect(series[0].key).toBe(FUNNEL_HISTOGRAM_SERIES_KEY)
        expect(series[0].label).toBe(FUNNEL_HISTOGRAM_SERIES_LABEL)
        expect(series[0].data).toEqual([12, 6, 2])
    })

    it('labels each bar with the humanized lower bound of its bin', () => {
        const { labels } = buildFunnelHistogramData(bins)

        expect(labels).toEqual(['0s', '1m', '2m'])
    })

    it('carries the per-bin percentage labels', () => {
        const { barLabels } = buildFunnelHistogramData(bins)

        expect(barLabels).toEqual(['60%', '30%', '10%'])
    })

    it('applies the provided series color', () => {
        const { series } = buildFunnelHistogramData(bins, { color: '#1d4aff' })

        expect(series[0].color).toBe('#1d4aff')
    })

    it('leaves the color unset when none is provided', () => {
        const { series } = buildFunnelHistogramData(bins)

        expect(series[0].color).toBeUndefined()
    })

    it('handles an empty bin list', () => {
        const { series, labels, barLabels } = buildFunnelHistogramData([])

        expect(labels).toEqual([])
        expect(barLabels).toEqual([])
        expect(series[0].data).toEqual([])
    })

    it('emits a second desaturated series for the previous period when comparing', () => {
        const { series, labels } = buildFunnelHistogramData(bins, {
            color: '#1d4aff',
            previous: { data: previousBins, color: '#cccccc' },
        })

        expect(series).toHaveLength(2)
        expect(series[0].key).toBe(FUNNEL_HISTOGRAM_SERIES_KEY)
        expect(series[0].label).toBe(FUNNEL_HISTOGRAM_CURRENT_SERIES_LABEL)
        expect(series[0].data).toEqual([12, 6, 2])
        expect(series[1].key).toBe(FUNNEL_HISTOGRAM_PREVIOUS_SERIES_KEY)
        expect(series[1].label).toBe(FUNNEL_HISTOGRAM_PREVIOUS_SERIES_LABEL)
        expect(series[1].data).toEqual([4, 5, 1])
        expect(series[1].color).toBe('#cccccc')
        // Shared bins: labels come from the (current) period's boundaries.
        expect(labels).toEqual(['0s', '1m', '2m'])
    })

    it('stays single-series when no previous period is provided', () => {
        const { series } = buildFunnelHistogramData(bins, { color: '#1d4aff' })

        expect(series).toHaveLength(1)
    })
})
