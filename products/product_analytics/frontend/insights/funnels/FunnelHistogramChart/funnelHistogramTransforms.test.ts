import type { HistogramGraphDatum } from '~/types'

import {
    buildFunnelHistogramData,
    FUNNEL_HISTOGRAM_SERIES_KEY,
    FUNNEL_HISTOGRAM_SERIES_LABEL,
} from './funnelHistogramTransforms'

const bins: HistogramGraphDatum[] = [
    { id: 0, bin0: 0, bin1: 60, count: 12, label: '60%' },
    { id: 60, bin0: 60, bin1: 120, count: 6, label: '30%' },
    { id: 120, bin0: 120, bin1: 180, count: 2, label: '10%' },
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
})
