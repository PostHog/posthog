import { dayjs } from 'lib/dayjs'

import {
    MarketingAnalyticsSearchQuery,
    MarketingAnalyticsSearchSource,
    MarketingAnalyticsSearchRow,
} from '~/queries/schema/schema-general'
import { ExternalDataSource, ExternalDataSourceSchema } from '~/types'

export type SearchPlatform = MarketingAnalyticsSearchSource['sourceType']
export type SearchMetrics = 'traffic' | 'conversions'
export type SearchBreakdown = NonNullable<MarketingAnalyticsSearchQuery['breakdown']>
export type SearchChannel = 'all' | 'paid' | 'organic'

export const SEARCH_PERFORMANCE_QUERY_KEY = 'marketing-search-performance'

export const SEARCH_PLATFORM_LABELS: Record<SearchPlatform, string> = {
    GoogleAds: 'Google Ads',
    BingAds: 'Bing Ads',
    GoogleSearchConsole: 'Google Search Console',
}

type SearchTableStatus = 'ready' | 'disabled' | 'pending' | 'failed' | 'paused' | 'billing' | 'stale'

function searchTableStatus(schema: ExternalDataSourceSchema | undefined): SearchTableStatus {
    if (!schema?.should_sync) {
        return 'disabled'
    }
    if (schema.status && ['Billing limits', 'Billing limits too low'].includes(schema.status)) {
        return 'billing'
    }
    if (schema.status === 'Failed') {
        return 'failed'
    }
    if (schema.status === 'Paused' || schema.status === 'Cancelled') {
        return 'paused'
    }
    if (!schema.table || !schema.last_synced_at || !dayjs(schema.last_synced_at).isValid()) {
        return 'pending'
    }
    const interval = schema.sync_frequency?.match(/^(\d+)(min|hour|day)$/)
    if (interval) {
        const unit = interval[2] === 'min' ? 'minute' : interval[2] === 'hour' ? 'hour' : 'day'
        if (
            dayjs(schema.last_synced_at)
                .add(Number(interval[1]) * 2, unit)
                .isBefore(dayjs())
        ) {
            return 'stale'
        }
    }
    return 'ready'
}

function searchTableNames(source: ExternalDataSource, breakdown: SearchBreakdown, detail: boolean): string[] {
    if (source.source_type === 'GoogleSearchConsole') {
        return detail
            ? ['search_analytics_by_query_page']
            : [
                  breakdown === 'page' ? 'search_analytics_by_page' : 'search_analytics_by_query',
                  'search_analytics_by_query_page',
              ]
    }
    if (source.source_type === 'GoogleAds') {
        return breakdown === 'page' ? ['landing_page_stats'] : ['keyword', 'keyword_stats']
    }
    return source.source_type === 'BingAds'
        ? [breakdown === 'page' ? 'destination_url_performance_report' : 'keyword_performance_report']
        : []
}

export function searchPerformanceSource(
    source: ExternalDataSource,
    breakdown: SearchBreakdown = 'keyword',
    detail = false
): MarketingAnalyticsSearchSource | null {
    const table = (name: string): string | undefined => {
        const schema = source.schemas.find((schema) => schema.name === name)
        return searchTableStatus(schema) === 'ready' ? (schema?.table?.hogql_name ?? schema?.table?.name) : undefined
    }
    const tables = searchTableNames(source, breakdown, detail).map(table)
    if (source.source_type === 'GoogleSearchConsole') {
        const index = tables.findIndex(Boolean)
        return index < 0
            ? null
            : { sourceType: 'GoogleSearchConsole', statsTable: tables[index]!, queryPageTable: detail || index === 1 }
    }
    if (tables.length === 0 || tables.some((table) => !table)) {
        return null
    }
    return source.source_type === 'GoogleAds'
        ? {
              sourceType: 'GoogleAds',
              statsTable: tables[tables.length - 1]!,
              ...(breakdown === 'keyword' ? { keywordTable: tables[0] } : {}),
          }
        : { sourceType: 'BingAds', statsTable: tables[0]! }
}

export function searchPerformanceSourceNotice(
    source: ExternalDataSource,
    breakdown: SearchBreakdown = 'keyword',
    detail = false
): string | null {
    const querySource = searchPerformanceSource(source, breakdown, detail)
    const fallback = querySource?.queryPageTable && !detail
    if (querySource && !fallback) {
        return null
    }
    const names = searchTableNames(source, breakdown, detail)
    const tablesByStatus = new Map<Exclude<SearchTableStatus, 'ready'>, string[]>()
    for (const name of names) {
        const status = searchTableStatus(source.schemas.find((schema) => schema.name === name))
        if (status !== 'ready') {
            tablesByStatus.set(status, [...(tablesByStatus.get(status) ?? []), name])
        }
    }
    const issues = [...tablesByStatus].map(([status, tables]) => {
        const tableNames = tables.join(' and ')
        return {
            disabled: `Enable ${tableNames} in the source settings.`,
            pending: `Waiting for the first sync of ${tableNames} to finish.`,
            failed: `The sync of ${tableNames} failed. Retry it in the source settings.`,
            billing: `A billing limit is blocking the sync of ${tableNames}. Check the source settings.`,
            paused: `Syncing has stopped for ${tableNames}. Resume it in the source settings.`,
            stale: `Data in ${tableNames} is out of date. Sync it again in the source settings.`,
        }[status]
    })
    const label = source.description || SEARCH_PLATFORM_LABELS[source.source_type as SearchPlatform]
    return `${label}: ${issues.join(' ')}${fallback ? ' Showing query-and-page data instead. Totals may differ from the dedicated query or page table.' : ' Data from this source will appear when the tables are ready.'}`
}

export const SEARCH_SOURCE_TYPES = ['GoogleAds', 'BingAds', 'GoogleSearchConsole']

export function selectedSearchSources(sources: ExternalDataSource[], selectedIds: string[]): ExternalDataSource[] {
    const searchSources = sources.filter((source) => SEARCH_SOURCE_TYPES.includes(source.source_type))
    const selected = searchSources.filter((source) => selectedIds.includes(source.id))
    return selectedIds.length > 0 ? selected : searchSources
}

export function searchPerformanceRowKey(row: MarketingAnalyticsSearchRow): string {
    return JSON.stringify([
        row.keyword ?? null,
        row.page ?? null,
        row.platform,
        row.matchType ?? null,
        row.currency ?? null,
    ])
}
