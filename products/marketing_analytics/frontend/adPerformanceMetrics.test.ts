import type { ExternalTable } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'
import { externalAdsCostTile } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingCostTile'

import { MarketingAnalyticsColumnsSchemaNames, SourceMap } from '~/queries/schema/schema-general'
import { DataWarehouseSettingsTab } from '~/types'

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

describe('External ad cost tiles', () => {
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
    ] as const)('keeps the external %s trend in the base currency', (metric, numerator, denominator) => {
        const top = externalAdsCostTile(table, 'USD', numerator)?.math_hogql
        const bottom = externalAdsCostTile(table, 'USD', denominator)?.math_hogql
        expect(externalAdsCostTile(table, 'USD', metric)?.math_hogql).toBe(`(${top}) / nullIf(${bottom}, 0)`)
        expect(externalAdsCostTile(table, 'USD', metric)?.math_hogql).toContain("convertCurrency('EUR', 'USD'")
    })
})
