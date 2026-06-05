import type { GraphDataset } from '~/types'

import { buildRevenueAnalyticsSeries } from './revenueAnalyticsChartTransforms'

const dataset = (overrides: Partial<GraphDataset> = {}): GraphDataset =>
    ({ id: 0, label: 'stripe.saas', data: [1, 2, 3], ...overrides }) as GraphDataset

describe('buildRevenueAnalyticsSeries', () => {
    it('maps a dataset onto a series with key, label, data and meta', () => {
        const [series] = buildRevenueAnalyticsSeries(
            [dataset({ id: 7, label: 'stripe.merch', data: [10, 20], days: ['2025-01-01', '2025-02-01'] })],
            { kind: 'line' }
        )

        expect(series).toMatchObject({
            key: '7',
            label: 'stripe.merch',
            data: [10, 20],
            meta: { days: ['2025-01-01', '2025-02-01'] },
        })
    })

    it('falls back to the array index for key and order when id/action are missing', () => {
        const series = buildRevenueAnalyticsSeries([dataset({ id: undefined }), dataset({ id: undefined })], {
            kind: 'line',
        })

        expect(series.map((s) => s.key)).toEqual(['0', '1'])
        expect(series.map((s) => s.meta?.order)).toEqual([0, 1])
    })

    it('prefers action.order over the array index', () => {
        const [series] = buildRevenueAnalyticsSeries([dataset({ action: { order: 5 } as GraphDataset['action'] })], {
            kind: 'bar',
        })

        expect(series.meta?.order).toBe(5)
    })

    it('adds an area fill only for the area kind', () => {
        expect(buildRevenueAnalyticsSeries([dataset()], { kind: 'area' })[0].fill).toEqual({})
        expect(buildRevenueAnalyticsSeries([dataset()], { kind: 'line' })[0].fill).toBeUndefined()
        expect(buildRevenueAnalyticsSeries([dataset()], { kind: 'bar' })[0].fill).toBeUndefined()
    })

    it('dashes the final segment for in-progress line/area charts', () => {
        expect(
            buildRevenueAnalyticsSeries([dataset({ data: [1, 2, 3] })], { kind: 'line', isInProgress: true })[0].stroke
        ).toEqual({
            partial: { fromIndex: 2 },
        })
        expect(buildRevenueAnalyticsSeries([dataset()], { kind: 'area', isInProgress: true })[0].stroke).toEqual({
            partial: { fromIndex: 2 },
        })
    })

    it('does not dash bars, complete charts, or single-point series', () => {
        expect(buildRevenueAnalyticsSeries([dataset()], { kind: 'bar', isInProgress: true })[0].stroke).toBeUndefined()
        expect(
            buildRevenueAnalyticsSeries([dataset()], { kind: 'line', isInProgress: false })[0].stroke
        ).toBeUndefined()
        expect(
            buildRevenueAnalyticsSeries([dataset({ data: [1] })], { kind: 'line', isInProgress: true })[0].stroke
        ).toBeUndefined()
    })

    it('applies the color override when provided and leaves color unset otherwise', () => {
        const withColor = buildRevenueAnalyticsSeries([dataset(), dataset({ id: 1 })], {
            kind: 'bar',
            getColor: (_, index) => (index === 0 ? '#abcdef' : undefined),
        })
        expect(withColor[0].color).toBe('#abcdef')
        expect(withColor[1].color).toBeUndefined()

        expect(buildRevenueAnalyticsSeries([dataset()], { kind: 'line' })[0].color).toBeUndefined()
    })

    it('tolerates a missing data array', () => {
        const [series] = buildRevenueAnalyticsSeries([dataset({ data: undefined })], { kind: 'line' })
        expect(series.data).toEqual([])
    })
})
