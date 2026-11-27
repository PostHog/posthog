import { urls } from 'scenes/urls'

// Sent as `entry_point` on the warehouse source connect events: renaming a value splits its attribution.
export type MarketingSourceConnectEntryPoint =
    | 'marketing_analytics_integration_menu'
    | 'marketing_analytics_recommendations'
    | 'marketing_analytics_search_console_card'
    | 'marketing_analytics_search_detail'
    | 'marketing_analytics_search_suggestions'
    | 'marketing_analytics_source_catalog'
    | 'marketing_analytics_source_setup_panel'

export function marketingSourceConnectUrl(
    sourceType: string,
    entryPoint: MarketingSourceConnectEntryPoint,
    returnUrl: string = urls.marketingAnalyticsApp()
): string {
    return urls.dataWarehouseSourceNew(sourceType, returnUrl, 'Marketing analytics', undefined, entryPoint)
}
