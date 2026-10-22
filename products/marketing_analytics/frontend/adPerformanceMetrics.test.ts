import type { ExternalTable } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'
import { externalAdsCostTile } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingCostTile'

import { MarketingAnalyticsColumnsSchemaNames, NodeKind, SourceMap } from '~/queries/schema/schema-general'
import { DataWarehouseSettingsTab, PropertyFilterType, PropertyOperator, TrendResult } from '~/types'

import { adPerformanceSparklines, buildAdPerformanceTrendsQuery } from './adPerformanceMetrics'

const row = (metric: string, data: number[], days = ['2026-01-01', '2026-01-02']): TrendResult =>
    ({
        action: { custom_name: metric },
        data,
        days,
        labels: days,
        label: metric,
        count: 0,
        aggregated_value: 0,
    }) as TrendResult

const table: ExternalTable = {
    id: 'table-one',
    source_map_id: 'source-one',
    name: 'example_ad_stats',
    source_type: 'manual',
    source_prefix: '',
    columns: [],
    url_pattern: '',
    sourceUrl: '',
    external_type: DataWarehouseSettingsTab.Managed,
    schema_name: 'example_ad_stats',
    dw_source_type: 'manual',
    source_map: {
        ...(Object.fromEntries(
            Object.values(MarketingAnalyticsColumnsSchemaNames).map((key) => [key, undefined])
        ) as SourceMap),
        date: 'day',
        cost: 'spend',
        clicks: 'clicks',
        impressions: 'impressions',
        reported_conversion: 'conversions',
        reported_conversion_value: 'revenue',
        currency: 'const:EUR',
    },
}

describe('Ad performance sparklines', () => {
    it('sums sources by date before calculating ratios and leaves zero denominators as gaps', () => {
        const metrics = adPerformanceSparklines([
            row('cost', [10, 20]),
            row('cost', [90, 30]),
            row('clicks', [5, 0]),
            row('clicks', [15, 0]),
            row('impressions', [200, 100]),
            row('reported_conversion', [2, 0]),
            row('reported_conversion_value', [300, 0]),
        ])
        expect(metrics.cost?.data).toEqual([100, 50])
        expect(metrics.cpc?.data).toEqual([5, NaN])
        expect(metrics.ctr?.data).toEqual([10, 0])
        expect(metrics.roas?.data).toEqual([3, 0])
        expect(metrics.cost_per_reported_conversion?.data).toEqual([50, NaN])
    })

    it('aligns dates, preserves unknown values, and excludes attributed goals and comparison periods', () => {
        const metrics = adPerformanceSparklines([
            row('cost', [20, 10], ['2026-01-02', '2026-01-01']),
            row('clicks', [5, NaN]),
            row('trial started', [100, 200]),
            { ...row('cost', [500, 600]), compare: true },
        ])
        expect(metrics.cost).toEqual({ labels: ['2026-01-01', '2026-01-02'], data: [10, 20] })
        expect(metrics.cpc?.data).toEqual([2, NaN])
        expect(Object.keys(metrics)).not.toContain('trial started')
    })

    it.each([false, true])('keeps request filters and current-period dates with precompute=%s', (precomputed) => {
        const query = buildAdPerformanceTrendsQuery(
            {
                kind: NodeKind.MarketingAnalyticsAggregatedQuery,
                properties: [],
                dateRange: { date_from: '-30d', date_to: null },
                compareFilter: { compare: true },
                integrationFilter: { integrationSourceIds: ['source-one'] },
            },
            'day',
            [],
            [table, { ...table, source_map_id: 'source-two' }],
            'USD',
            precomputed
        )
        expect(query.series).toHaveLength(5)
        expect(query.dateRange).toEqual({ date_from: '-30d', date_to: null })
        expect(query.compareFilter).toBeUndefined()
        if (precomputed) {
            expect(query.series[0].properties).toContainEqual({
                type: PropertyFilterType.DataWarehouse,
                key: 'source_id',
                operator: PropertyOperator.Exact,
                value: ['source-one'],
            })
        } else {
            expect(query.series.every((series) => 'table_name' in series && series.table_name === table.name)).toBe(
                true
            )
            expect((query.series[0] as { math_hogql: string }).math_hogql).toContain('convertCurrency')
            expect((query.series[1] as { math_hogql: string }).math_hogql).not.toContain('convertCurrency')
            expect((query.series[3] as { math_hogql: string }).math_hogql).not.toContain('convertCurrency')
        }
    })

    it.each([
        [
            'cost_per_reported_conversion',
            MarketingAnalyticsColumnsSchemaNames.Cost,
            MarketingAnalyticsColumnsSchemaNames.ReportedConversion,
        ],
        [
            'roas',
            MarketingAnalyticsColumnsSchemaNames.ReportedConversionValue,
            MarketingAnalyticsColumnsSchemaNames.Cost,
        ],
    ] as const)(
        'keeps the external %s trend in the same currency as its sparkline',
        (metric, numerator, denominator) => {
            const top = externalAdsCostTile(table, 'USD', numerator)?.math_hogql
            const bottom = externalAdsCostTile(table, 'USD', denominator)?.math_hogql
            expect(externalAdsCostTile(table, 'USD', metric)?.math_hogql).toBe(`(${top}) / nullIf(${bottom}, 0)`)
            expect(externalAdsCostTile(table, 'USD', metric)?.math_hogql).toContain("convertCurrency('EUR', 'USD'")
        }
    )

    it('does not request data when there are no supported sources', () => {
        expect(
            buildAdPerformanceTrendsQuery(
                { kind: NodeKind.MarketingAnalyticsAggregatedQuery, properties: [] },
                'day',
                [],
                [],
                'USD',
                false
            ).series
        ).toEqual([])
    })
})
