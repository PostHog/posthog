import type { LegendItem } from '@posthog/quill-charts'

import type { GraphDataset } from '~/types'

import {
    buildRevenueAnalyticsSeries,
    orderLegendItems,
    type RevenueAnalyticsChartKind,
} from './revenueAnalyticsChartTransforms'

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

    it.each<{ kind: RevenueAnalyticsChartKind; expectedFill: Record<string, never> | undefined }>([
        { kind: 'area', expectedFill: {} },
        { kind: 'line', expectedFill: undefined },
        { kind: 'bar', expectedFill: undefined },
    ])('adds an area fill only for the area kind (kind=$kind)', ({ kind, expectedFill }) => {
        expect(buildRevenueAnalyticsSeries([dataset()], { kind })[0].fill).toEqual(expectedFill)
    })

    it.each<{
        name: string
        kind: RevenueAnalyticsChartKind
        data: number[]
        isInProgress: boolean
        expectedStroke: { partial: { fromIndex: number } } | undefined
    }>([
        {
            name: 'line in-progress dashes the final segment',
            kind: 'line',
            data: [1, 2, 3],
            isInProgress: true,
            expectedStroke: { partial: { fromIndex: 2 } },
        },
        {
            name: 'area in-progress dashes the final segment',
            kind: 'area',
            data: [1, 2, 3],
            isInProgress: true,
            expectedStroke: { partial: { fromIndex: 2 } },
        },
        {
            name: 'bars never dash',
            kind: 'bar',
            data: [1, 2, 3],
            isInProgress: true,
            expectedStroke: undefined,
        },
        {
            name: 'complete (not in-progress) charts do not dash',
            kind: 'line',
            data: [1, 2, 3],
            isInProgress: false,
            expectedStroke: undefined,
        },
        {
            name: 'single-point series do not dash',
            kind: 'line',
            data: [1],
            isInProgress: true,
            expectedStroke: undefined,
        },
    ])('$name', ({ kind, data, isInProgress, expectedStroke }) => {
        expect(buildRevenueAnalyticsSeries([dataset({ data })], { kind, isInProgress })[0].stroke).toEqual(
            expectedStroke
        )
    })

    it('applies the color override when provided and leaves color unset otherwise', () => {
        const colorByIndex: (string | undefined)[] = ['#abcdef', undefined]
        const withColor = buildRevenueAnalyticsSeries([dataset(), dataset({ id: 1 })], {
            kind: 'bar',
            getColor: (_, index) => colorByIndex[index],
        })
        expect(withColor[0].color).toBe('#abcdef')
        expect(withColor[1].color).toBeUndefined()

        expect(buildRevenueAnalyticsSeries([dataset()], { kind: 'line' })[0].color).toBeUndefined()
    })

    it('forwards action and breakdown_value onto series meta', () => {
        const action = { order: 2, id: 42 } as GraphDataset['action']
        const [series] = buildRevenueAnalyticsSeries([dataset({ action, breakdown_value: 'stripe.saas' })], {
            kind: 'line',
        })

        expect(series.meta?.action).toBe(action)
        expect(series.meta?.breakdown_value).toBe('stripe.saas')
    })

    it('keeps a falsy-but-valid id as the key rather than the index', () => {
        const series = buildRevenueAnalyticsSeries([dataset({ id: 0 }), dataset({ id: 0 })], { kind: 'line' })
        expect(series.map((s) => s.key)).toEqual(['0', '0'])
    })

    it('tolerates a missing data array', () => {
        const [series] = buildRevenueAnalyticsSeries([dataset({ data: undefined })], { kind: 'line' })
        expect(series.data).toEqual([])
    })
})

describe('orderLegendItems', () => {
    const items = [{ label: 'a' }, { label: 'b' }, { label: 'c' }] as LegendItem[]

    it('reverses the items when reverse is true', () => {
        expect(orderLegendItems(items, true).map((i) => i.label)).toEqual(['c', 'b', 'a'])
    })

    it.each([{ reverse: false }, { reverse: undefined }])(
        'keeps the original order when reverse=$reverse',
        ({ reverse }) => {
            expect(orderLegendItems(items, reverse).map((i) => i.label)).toEqual(['a', 'b', 'c'])
        }
    )

    it('does not mutate the input array', () => {
        const input = [{ label: 'a' }, { label: 'b' }] as LegendItem[]
        orderLegendItems(input, true)
        expect(input.map((i) => i.label)).toEqual(['a', 'b'])
    })
})
