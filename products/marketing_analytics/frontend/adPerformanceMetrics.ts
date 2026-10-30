import { getResultSeries } from 'scenes/insights/utils/resultSeries'
import type {
    ExternalTable,
    NativeSource,
} from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'
import { externalAdsCostTile } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingCostTile'
import {
    MarketingDashboardMapper,
    type validColumnsForTiles,
} from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/utils'

import {
    DataWarehouseNode,
    MarketingAnalyticsAggregatedQuery,
    MarketingAnalyticsBaseColumns,
    MarketingAnalyticsColumnsSchemaNames,
    NodeKind,
    TrendsQuery,
} from '~/queries/schema/schema-general'
import {
    ChartDisplayType,
    HogQLMathType,
    IntervalType,
    PropertyFilterType,
    PropertyOperator,
    TrendResult,
} from '~/types'

export const AD_PERFORMANCE_METRICS: Record<string, validColumnsForTiles> = {
    [MarketingAnalyticsBaseColumns.Cost]: MarketingAnalyticsColumnsSchemaNames.Cost,
    [MarketingAnalyticsBaseColumns.Clicks]: MarketingAnalyticsColumnsSchemaNames.Clicks,
    [MarketingAnalyticsBaseColumns.Impressions]: MarketingAnalyticsColumnsSchemaNames.Impressions,
    [MarketingAnalyticsBaseColumns.ReportedConversions]: MarketingAnalyticsColumnsSchemaNames.ReportedConversion,
    [MarketingAnalyticsBaseColumns.ReportedConversionValue]:
        MarketingAnalyticsColumnsSchemaNames.ReportedConversionValue,
    [MarketingAnalyticsBaseColumns.CPC]: 'cpc',
    [MarketingAnalyticsBaseColumns.CTR]: 'ctr',
    [MarketingAnalyticsBaseColumns.ReportedROAS]: 'roas',
    [MarketingAnalyticsBaseColumns.CostPerReportedConversions]: 'cost_per_reported_conversion',
}

export function adPerformanceMetricKey(key: string): validColumnsForTiles | undefined {
    return Object.hasOwn(AD_PERFORMANCE_METRICS, key) ? AD_PERFORMANCE_METRICS[key] : undefined
}

const RAW_METRICS = [
    MarketingAnalyticsColumnsSchemaNames.Cost,
    MarketingAnalyticsColumnsSchemaNames.Clicks,
    MarketingAnalyticsColumnsSchemaNames.Impressions,
    MarketingAnalyticsColumnsSchemaNames.ReportedConversion,
    MarketingAnalyticsColumnsSchemaNames.ReportedConversionValue,
] as const
const PRECOMPUTED_FIELDS = [
    'cost',
    'clicks',
    'impressions',
    'reported_conversions',
    'reported_conversion_value',
] as const

export interface AdPerformanceSparkline {
    data: number[]
    labels: string[]
}

export function buildAdPerformanceTrendsQuery(
    query: MarketingAnalyticsAggregatedQuery,
    interval: IntervalType,
    nativeSources: NativeSource[],
    externalTables: ExternalTable[],
    baseCurrency: string,
    precomputed: boolean
): TrendsQuery {
    const selectedIds = query.integrationFilter?.integrationSourceIds ?? []
    const native = nativeSources.filter((source) => !selectedIds.length || selectedIds.includes(source.source.id))
    const external = externalTables.filter((table) => !selectedIds.length || selectedIds.includes(table.source_map_id))
    const series: DataWarehouseNode[] = []
    if (native.length || external.length) {
        RAW_METRICS.forEach((metric, index) => {
            const nodes: DataWarehouseNode[] = precomputed
                ? [
                      {
                          kind: NodeKind.DataWarehouseNode,
                          id: 'marketing_costs_precomputed',
                          table_name: 'marketing_costs_precomputed',
                          id_field: 'campaign_id',
                          distinct_id_field: 'campaign_id',
                          timestamp_field: 'timestamp',
                          math: HogQLMathType.HogQL,
                          math_hogql: `sum(${PRECOMPUTED_FIELDS[index]})`,
                          properties: [
                              { type: PropertyFilterType.HogQL, key: "grain = 'campaign' AND expires_at > today()" },
                              ...(selectedIds.length
                                  ? [
                                        {
                                            type: PropertyFilterType.DataWarehouse as const,
                                            key: 'source_id',
                                            operator: PropertyOperator.Exact,
                                            value: selectedIds,
                                        },
                                    ]
                                  : []),
                          ],
                      },
                  ]
                : [
                      ...native.map((source) => MarketingDashboardMapper(source, metric, baseCurrency)),
                      ...external.map((table) => externalAdsCostTile(table, baseCurrency, metric)),
                  ].filter((node): node is DataWarehouseNode => node !== null)
            series.push(...nodes.map((node) => ({ ...node, custom_name: metric })))
        })
    }
    return {
        kind: NodeKind.TrendsQuery,
        series,
        interval,
        dateRange: query.dateRange,
        trendsFilter: { display: ChartDisplayType.ActionsLineGraph },
        tags: query.tags,
    }
}

export function adPerformanceSparklines(
    query: TrendsQuery,
    results: TrendResult[]
): Partial<Record<validColumnsForTiles, AdPerformanceSparkline>> {
    const buckets = new Map<string, Map<string, number>>()
    for (const row of results) {
        // `buildAdPerformanceTrendsQuery` names each series after the metric it reads
        const metric = getResultSeries(query, row).node?.custom_name
        if (row.compare || !metric || !RAW_METRICS.some((key) => key === metric)) {
            continue
        }
        const values = buckets.get(metric) ?? new Map<string, number>()
        row.days.forEach((day, index) => {
            const value = row.data[index]
            values.set(
                day,
                (values.get(day) ?? 0) + (typeof value === 'number' && Number.isFinite(value) ? value : NaN)
            )
        })
        buckets.set(metric, values)
    }
    const labels = [...new Set([...buckets.values()].flatMap((values) => [...values.keys()]))].sort()
    const output: Partial<Record<validColumnsForTiles, AdPerformanceSparkline>> = {}
    const add = (metric: validColumnsForTiles, data: number[]): void => {
        if (data.some(Number.isFinite)) {
            output[metric] = { data, labels }
        }
    }
    for (const metric of RAW_METRICS) {
        const values = buckets.get(metric)
        if (values) {
            add(
                metric,
                labels.map((label) => values.get(label) ?? NaN)
            )
        }
    }
    const ratio = (
        metric: validColumnsForTiles,
        numerator: (typeof RAW_METRICS)[number],
        denominator: (typeof RAW_METRICS)[number],
        scale = 1
    ): void => {
        const top = output[numerator]?.data
        const bottom = output[denominator]?.data
        if (top && bottom) {
            add(
                metric,
                top.map((value, index) => (bottom[index] ? (value / bottom[index]) * scale : NaN))
            )
        }
    }
    ratio('cpc', MarketingAnalyticsColumnsSchemaNames.Cost, MarketingAnalyticsColumnsSchemaNames.Clicks)
    ratio('ctr', MarketingAnalyticsColumnsSchemaNames.Clicks, MarketingAnalyticsColumnsSchemaNames.Impressions, 100)
    ratio(
        'roas',
        MarketingAnalyticsColumnsSchemaNames.ReportedConversionValue,
        MarketingAnalyticsColumnsSchemaNames.Cost
    )
    ratio(
        'cost_per_reported_conversion',
        MarketingAnalyticsColumnsSchemaNames.Cost,
        MarketingAnalyticsColumnsSchemaNames.ReportedConversion
    )
    return output
}
