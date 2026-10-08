import { MarketingAnalyticsSearchQuery, MarketingAnalyticsSearchSource } from '~/queries/schema/schema-general'
import { ExternalDataSource } from '~/types'

export type SearchPlatform = MarketingAnalyticsSearchSource['sourceType']
export type SearchMetrics = 'traffic' | 'conversions'
export type SearchBreakdown = NonNullable<MarketingAnalyticsSearchQuery['breakdown']>
export type SearchChannel = 'all' | 'paid' | 'organic'

export const SEARCH_PLATFORM_LABELS: Record<SearchPlatform, string> = {
    GoogleAds: 'Google Ads',
    BingAds: 'Bing Ads',
    GoogleSearchConsole: 'Google Search Console',
}

export function searchPerformanceSource(
    source: ExternalDataSource,
    breakdown: SearchBreakdown = 'keyword',
    detail = false
): MarketingAnalyticsSearchSource | null {
    const table = (name: string): string | undefined => {
        const schema = source.schemas.find((schema) => schema.name === name && schema.should_sync && schema.table)
        return schema?.table?.hogql_name ?? schema?.table?.name
    }
    if (source.source_type === 'GoogleSearchConsole') {
        const queryPage = table('search_analytics_by_query_page')
        const aggregate = detail
            ? undefined
            : table(breakdown === 'page' ? 'search_analytics_by_page' : 'search_analytics_by_query')
        const statsTable = aggregate ?? queryPage
        return statsTable ? { sourceType: 'GoogleSearchConsole', statsTable, queryPageTable: !aggregate } : null
    }
    if (source.source_type === 'GoogleAds') {
        if (breakdown === 'page') {
            const statsTable = table('landing_page_stats')
            return statsTable ? { sourceType: 'GoogleAds', statsTable } : null
        }
        const statsTable = table('keyword_stats')
        const keywordTable = table('keyword')
        return statsTable && keywordTable ? { sourceType: 'GoogleAds', statsTable, keywordTable } : null
    }
    if (source.source_type === 'BingAds' && breakdown === 'keyword') {
        const statsTable = table('keyword_performance_report')
        return statsTable ? { sourceType: 'BingAds', statsTable } : null
    }
    return null
}

export const SEARCH_SOURCE_TYPES = ['GoogleAds', 'BingAds', 'GoogleSearchConsole']

export function selectedSearchSources(sources: ExternalDataSource[], selectedIds: string[]): ExternalDataSource[] {
    const searchSources = sources.filter((source) => SEARCH_SOURCE_TYPES.includes(source.source_type))
    const selected = searchSources.filter((source) => selectedIds.includes(source.id))
    return selectedIds.length > 0 ? selected : searchSources
}

export function requiredSearchTables(source: ExternalDataSource, breakdown: SearchBreakdown): string {
    if (source.source_type === 'GoogleSearchConsole') {
        return breakdown === 'page'
            ? 'search_analytics_by_page or search_analytics_by_query_page'
            : 'search_analytics_by_query or search_analytics_by_query_page'
    }
    return source.source_type === 'GoogleAds'
        ? breakdown === 'page'
            ? 'landing_page_stats'
            : 'keyword and keyword_stats'
        : 'keyword_performance_report'
}
