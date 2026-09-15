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

// Mirrors insightDataLogic, which keeps the API's `results` and adds `result` as a copy.
function response(results: unknown[]): AnyResponseType {
    return { results, result: results } as AnyResponseType
}

// The preview canvas rebuilds `result` from `results`, so a derivation that only sets one key renders the wrong rows.
function results(preview: ChartPreviewData | null): TrendResult[] {
    if (!preview) {
        throw new Error('Expected a preview')
    }
    const { results, result } = preview.response as { results: TrendResult[]; result: TrendResult[] }
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

    it.each([
        ['total', 10],
        ['sum', 10],
        ['dau', 10],
        ['monthly_active', 4],
        ['avg', 2.5],
        ['min', 1],
    ])('totals a %s series as %s', (math, value) => {
        const preview = deriveChartPreview(
            ChartDisplayType.BoldNumber,
            query(ChartDisplayType.ActionsLineGraph),
            response([series({ math })])
        )
        expect(results(preview)[0]).toMatchObject({ data: [], aggregated_value: value })
    })

    it('folds breakdown rows into one series for single-series displays', () => {
        const source = query(ChartDisplayType.ActionsLineGraph, {
            breakdownFilter: { breakdown: '$browser', breakdown_type: 'event' },
        })
        const rows = [series({ breakdown_value: 'Chrome' }), series({ breakdown_value: 'Safari', data: [10, 0, 0, 0] })]

        const metric = deriveChartPreview(ChartDisplayType.Metric, source, response(rows))
        expect(results(metric)).toHaveLength(1)
        expect(results(metric)[0]).toMatchObject({ data: [11, 2, 3, 4] })
        expect(results(metric)[0]).not.toHaveProperty('breakdown_value')

        const pie = deriveChartPreview(ChartDisplayType.ActionsPie, source, response(rows))
        expect(results(pie)).toHaveLength(2)
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

    it('renders the map from a loaded country breakdown', () => {
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
        const loaded = response([series({ data: [], aggregated_value: 42 })])
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
})
