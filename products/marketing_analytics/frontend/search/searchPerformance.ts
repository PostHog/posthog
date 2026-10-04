import { MarketingAnalyticsSearchSource } from '~/queries/schema/schema-general'
import { ExternalDataSource } from '~/types'

export type SearchPlatform = MarketingAnalyticsSearchSource['sourceType']
export type SearchMetrics = 'traffic' | 'conversions'

export const SEARCH_PLATFORM_LABELS: Record<SearchPlatform, string> = {
    GoogleAds: 'Google Ads',
    BingAds: 'Bing Ads',
}

export function searchPerformanceSource(source: ExternalDataSource): MarketingAnalyticsSearchSource | null {
    const table = (name: string): string | undefined => {
        const schema = source.schemas.find((schema) => schema.name === name && schema.should_sync && schema.table)
        return schema?.table?.hogql_name ?? schema?.table?.name
    }
    if (source.source_type === 'GoogleAds') {
        const statsTable = table('keyword_stats')
        const keywordTable = table('keyword')
        return statsTable && keywordTable ? { sourceType: 'GoogleAds', statsTable, keywordTable } : null
    }
    if (source.source_type === 'BingAds') {
        const statsTable = table('keyword_performance_report')
        return statsTable ? { sourceType: 'BingAds', statsTable } : null
    }
    return null
}

export const SEARCH_SOURCE_TYPES = ['GoogleAds', 'BingAds']

export function selectedSearchSources(sources: ExternalDataSource[], selectedIds: string[]): ExternalDataSource[] {
    const searchSources = sources.filter((source) => SEARCH_SOURCE_TYPES.includes(source.source_type))
    const selected = searchSources.filter((source) => selectedIds.includes(source.id))
    return selected.length > 0 ? selected : searchSources
}
