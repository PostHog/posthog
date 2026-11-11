import type { validColumnsForTiles } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/utils'

import { MarketingAnalyticsBaseColumns, MarketingAnalyticsColumnsSchemaNames } from '~/queries/schema/schema-general'

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
