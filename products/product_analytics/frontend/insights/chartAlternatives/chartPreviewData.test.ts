import type { AnyResponseType, TrendsQuery } from '~/queries/schema/schema-general'
import { NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType, CompareLabelType } from '~/types'
import type { TrendResult } from '~/types'

import { deriveChartPreview } from './chartPreviewData'
import type { ChartPreviewData } from './chartPreviewData'

function series(overrides: Partial<TrendResult> & { math?: string }): TrendResult {
    const { math = 'total', ...rest } = overrides
    return {
        action: { id: '$pageview', type: 'events', order: 0, math } as TrendResult['action'],
        label: '$pageview',
        data: [1, 2, 3, 4],
        days: ['2026-01-01', '2026-01-02', '2026-01-03', '2026-01-04'],
        labels: ['1-Jan', '2-Jan', '3-Jan', '4-Jan'],
        count: 10,
        aggregated_value: 0,
        ...rest,
    } as TrendResult
}

function query(display: ChartDisplayType, overrides: Partial<TrendsQuery> = {}): TrendsQuery {
    return {
        kind: NodeKind.TrendsQuery,
        series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
        trendsFilter: { display },
        ...overrides,
    }
}

function response(results: unknown[], hasMore = false): AnyResponseType {
    return { results, result: results, hasMore } as AnyResponseType
}

// The preview canvas rebuilds `result` from `results`, so a derivation that only sets one key renders the wrong rows.
function results(preview: ChartPreviewData | null): TrendResult[] {
    const { results, result } = preview!.response as { results: TrendResult[]; result: TrendResult[] }
    expect(result).toBe(results)
    return results
}

describe('deriveChartPreview', () => {
    it.each([
        ['cumulative', ChartDisplayType.ActionsLineGraphCumulative, [1, 3, 6, 10], 10],
        ['slope', ChartDisplayType.SlopeGraph, [1, 4], 10],
    ])('derives the %s series exactly from the loaded time series', (_, display, data, count) => {
        const preview = deriveChartPreview(display, query(ChartDisplayType.ActionsLineGraph), response([series({})]))
        expect(preview?.sample).toBe(false)
        expect(results(preview)[0]).toMatchObject({ data, count })
    })

    it.each(['total', 'sum'])('derives a %s total from raw buckets', (math) => {
        const preview = deriveChartPreview(
            ChartDisplayType.BoldNumber,
            query(ChartDisplayType.ActionsLineGraph),
            response([series({ math })])
        )
        expect(results(preview)[0]).toMatchObject({ data: [], aggregated_value: 10 })
    })

    it.each([
        ['distinct users', 'dau', {}],
        ['average', 'avg', {}],
        ['percentile', 'p90', {}],
        ['formula', 'total', { trendsFilter: { formula: 'A / B' } }],
        ['smoothed buckets', 'total', { trendsFilter: { smoothingIntervals: 2 } }],
        ['sampled buckets', 'total', { samplingFactor: 0.1 }],
    ])('does not reconstruct a total from %s', (_, math, queryOverrides) => {
        expect(
            deriveChartPreview(
                ChartDisplayType.BoldNumber,
                query(ChartDisplayType.ActionsLineGraph, queryOverrides),
                response([series({ math })])
            )
        ).toBeNull()
    })

    it.each([ChartDisplayType.BoldNumber, ChartDisplayType.Metric])(
        'does not fold breakdown rows to preview %s',
        (display) => {
            const source = query(ChartDisplayType.ActionsLineGraph, {
                breakdownFilter: { breakdown: '$browser', breakdown_type: 'event' },
            })
            const rows = [
                series({ breakdown_value: 'Chrome' }),
                series({ breakdown_value: 'Safari', data: [10, 0, 0, 0] }),
            ]

            expect(deriveChartPreview(display, source, response(rows))).toBeNull()
        }
    )

    it('keeps breakdown totals separate when the target supports a breakdown', () => {
        const source = query(ChartDisplayType.ActionsLineGraph, {
            breakdownFilter: { breakdown: '$browser', breakdown_type: 'event' },
        })
        const rows = [series({ breakdown_value: 'Chrome' }), series({ breakdown_value: 'Safari', data: [10, 0, 0, 0] })]

        const pie = deriveChartPreview(ChartDisplayType.ActionsPie, source, response(rows))
        expect(results(pie).map((row) => [row.breakdown_value, row.aggregated_value])).toEqual([
            ['Chrome', 10],
            ['Safari', 10],
        ])
    })

    it.each([ChartDisplayType.WorldMap, ChartDisplayType.CalendarHeatmap, ChartDisplayType.BoxPlot])(
        'shows sample data for %s instead of querying',
        (display) => {
            const preview = deriveChartPreview(
                display,
                query(ChartDisplayType.ActionsLineGraph),
                response([series({})])
            )
            expect(preview?.sample).toBe(true)
            expect(results(preview).length).toBeGreaterThan(0)
        }
    )

    it('renders a complete country breakdown as a live map', () => {
        const preview = deriveChartPreview(
            ChartDisplayType.WorldMap,
            query(ChartDisplayType.ActionsLineGraph, {
                breakdownFilter: { breakdown: '$geoip_country_code', breakdown_type: 'event' },
            }),
            response([series({ breakdown_value: 'US' }), series({ breakdown_value: 'GB', data: [5, 5, 0, 0] })])
        )
        expect(preview?.sample).toBe(false)
        expect(results(preview).map((r) => [r.breakdown_value, r.aggregated_value])).toEqual([
            ['US', 10],
            ['GB', 10],
        ])
    })

    it('uses sample map data when the country breakdown is truncated', () => {
        expect(
            deriveChartPreview(
                ChartDisplayType.WorldMap,
                query(ChartDisplayType.ActionsLineGraph, {
                    breakdownFilter: { breakdown: '$geoip_country_code', breakdown_type: 'event' },
                }),
                response([series({ breakdown_value: 'US' })], true)
            )?.sample
        ).toBe(true)
    })

    it('drops the previous-period series the metric runner adds unless the query compares', () => {
        const rows = [
            series({ compare_label: CompareLabelType.Current }),
            series({ compare_label: CompareLabelType.Previous, data: [9, 9, 9, 9] }),
        ]
        const source = query(ChartDisplayType.Metric)

        const line = deriveChartPreview(ChartDisplayType.ActionsLineGraph, source, response(rows))
        expect(results(line)).toHaveLength(1)
        expect(results(line)[0]).not.toHaveProperty('compare_label')

        const comparing = deriveChartPreview(
            ChartDisplayType.ActionsLineGraph,
            query(ChartDisplayType.Metric, { compareFilter: { compare: true } }),
            response(rows)
        )
        expect(results(comparing)).toHaveLength(2)
    })

    it('derives time series tiles from the remembered time series when only a total value is loaded', () => {
        const loaded = response([series({ math: 'dau', data: [], aggregated_value: 42 })])
        const remembered = response([
            series({ compare_label: CompareLabelType.Current }),
            series({ compare_label: CompareLabelType.Previous }),
        ])
        const source = query(ChartDisplayType.ActionsPie)

        expect(deriveChartPreview(ChartDisplayType.ActionsLineGraph, source, loaded)).toBeNull()
        expect(deriveChartPreview(ChartDisplayType.BoldNumber, source, loaded)).toEqual({
            response: loaded,
            sample: false,
        })

        const line = deriveChartPreview(ChartDisplayType.ActionsLineGraph, source, loaded, remembered)
        expect(line?.sample).toBe(false)
        expect(results(line!)).toHaveLength(1)
        expect(results(line!)[0]).toMatchObject({ data: [1, 2, 3, 4] })

        const cumulative = deriveChartPreview(ChartDisplayType.ActionsLineGraphCumulative, source, loaded, remembered)
        expect(results(cumulative!)[0]).toMatchObject({ data: [1, 3, 6, 10] })
    })

    it.each([
        ['cumulative', ChartDisplayType.ActionsLineGraphCumulative, [1, 3, 6, 10]],
        ['slope', ChartDisplayType.SlopeGraph, [1, 4]],
    ])('does not treat transformed %s output as raw buckets', (_, sourceDisplay, data) => {
        const source = query(sourceDisplay)
        const transformed = response([series({ data })])

        expect(deriveChartPreview(ChartDisplayType.BoldNumber, source, transformed)).toBeNull()

        const preview = deriveChartPreview(ChartDisplayType.BoldNumber, source, transformed, response([series({})]))
        expect(results(preview)[0]).toMatchObject({ aggregated_value: 10 })
    })

    it.each([
        ['smoothed buckets', query(ChartDisplayType.ActionsLineGraph, { trendsFilter: { smoothingIntervals: 2 } })],
        [
            'breakdown buckets',
            query(ChartDisplayType.ActionsLineGraph, {
                breakdownFilter: { breakdown: '$browser', breakdown_type: 'event' },
            }),
        ],
    ])('does not derive a slope from %s', (_, source) => {
        expect(deriveChartPreview(ChartDisplayType.SlopeGraph, source, response([series({})]))).toBeNull()
    })
})
