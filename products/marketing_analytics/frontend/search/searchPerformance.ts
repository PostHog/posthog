import { dayjs } from 'lib/dayjs'

import {
    MarketingAnalyticsSearchQuery,
    MarketingAnalyticsSearchSource,
    MarketingAnalyticsSearchRow,
} from '~/queries/schema/schema-general'
import { HogQLQueryString, escapePropertyAsHogQLIdentifier, hogql } from '~/queries/utils'
import { ExternalDataSchemaStatus, ExternalDataSource, ExternalDataSourceSchema } from '~/types'

export type SearchPlatform = MarketingAnalyticsSearchSource['sourceType']
export type SearchMetrics = 'traffic' | 'conversions'
export type SearchBreakdown = NonNullable<MarketingAnalyticsSearchQuery['breakdown']>
export type SearchChannel = 'all' | 'paid' | 'organic'

export const SEARCH_PERFORMANCE_QUERY_KEY = 'marketing-search-performance'

/** Google Ads channel types (`campaign_advertising_channel_type`) present in each source's campaign table. */
export type CampaignChannelTypes = Record<ExternalDataSource['id'], string[]>

const SEARCH_TERM_TABLES = [
    { channelType: 'SEARCH', table: 'search_term_stats', campaigns: 'Search', label: 'search terms table' },
    {
        channelType: 'PERFORMANCE_MAX',
        table: 'performance_max_search_term_stats',
        campaigns: 'Performance Max',
        label: 'Performance Max search terms table',
    },
] as const

export const SEARCH_PLATFORM_LABELS: Record<SearchPlatform, string> = {
    GoogleAds: 'Google Ads',
    BingAds: 'Bing Ads',
    GoogleSearchConsole: 'Google Search Console',
}

type SearchTableStatus = 'ready' | 'empty' | 'disabled' | 'pending' | 'failed' | 'paused' | 'billing' | 'stale'

/** How a notice reads: a problem to fix, data still arriving, or a fact about the account. */
export type SearchNoticeKind = 'attention' | 'syncing' | 'info'

export interface SearchNotice {
    message: string
    kind: SearchNoticeKind
}

const ATTENTION_STATES: string[] = ['missing', 'disabled', 'failed', 'billing', 'paused', 'stale']

function noticeKind(states: string[]): SearchNoticeKind {
    return states.some((state) => ATTENTION_STATES.includes(state)) ? 'attention' : 'syncing'
}

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
    const synced = !!schema.last_synced_at && dayjs(schema.last_synced_at).isValid()
    if (!schema.table) {
        // A finished sync that returned no rows creates no warehouse table.
        return synced && schema.status === ExternalDataSchemaStatus.Completed ? 'empty' : 'pending'
    }
    if (!synced) {
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

function readyTable(source: ExternalDataSource, name: string): string | undefined {
    const schema = source.schemas.find((schema) => schema.name === name)
    return searchTableStatus(schema) === 'ready' ? (schema?.table?.hogql_name ?? schema?.table?.name) : undefined
}

function searchTableNames(source: ExternalDataSource, breakdown: SearchBreakdown, detail: boolean): string[] {
    if (source.source_type === 'GoogleSearchConsole') {
        return detail
            ? ['search_analytics_by_query_page']
            : [breakdown === 'page' ? 'search_analytics_by_page' : 'search_analytics_by_query']
    }
    if (source.source_type === 'GoogleAds') {
        return breakdown === 'page'
            ? ['landing_page_stats']
            : breakdown === 'search_term'
              ? ['campaign']
              : ['keyword', 'keyword_stats']
    }
    return source.source_type === 'BingAds' && breakdown !== 'search_term'
        ? [breakdown === 'page' ? 'destination_url_performance_report' : 'keyword_performance_report']
        : []
}

function googleSearchTermsSource(source: ExternalDataSource): MarketingAnalyticsSearchSource | null {
    const campaignTable = readyTable(source, 'campaign')
    const searchTermTable = readyTable(source, 'search_term_stats')
    const performanceMaxSearchTermTable = readyTable(source, 'performance_max_search_term_stats')
    if (!campaignTable || !(searchTermTable || performanceMaxSearchTermTable)) {
        return null
    }
    return {
        sourceType: 'GoogleAds',
        statsTable: campaignTable,
        ...(searchTermTable ? { searchTermTable } : {}),
        ...(performanceMaxSearchTermTable ? { performanceMaxSearchTermTable } : {}),
    }
}

export type SearchTermTableState = 'missing' | Exclude<SearchTableStatus, 'pending'> | 'syncing' | 'empty'

export interface SearchTermTable {
    table: string
    campaigns: string
    label: string
    state: SearchTermTableState
    schemaId?: string
}

export function campaignChannelTypesQuery(source: ExternalDataSource): HogQLQueryString | null {
    const table = source.source_type === 'GoogleAds' ? readyTable(source, 'campaign') : undefined
    if (!table) {
        return null
    }
    const tableIdentifier = table.split('.').map(escapePropertyAsHogQLIdentifier).join('.')
    return hogql`SELECT groupUniqArray(campaign_advertising_channel_type) FROM ${hogql.raw(tableIdentifier)}`
}

/** The search term tables this Google Ads account needs, given the campaign types it runs. */
function searchTermTables(source: ExternalDataSource, channelTypes: string[]): SearchTermTable[] {
    return SEARCH_TERM_TABLES.filter(({ channelType }) => channelTypes.includes(channelType)).map(
        ({ table, campaigns, label }) => {
            const schema = source.schemas.find((schema) => schema.name === table)
            const status = searchTableStatus(schema)
            return {
                table,
                campaigns,
                label,
                state: !schema ? 'missing' : status === 'pending' ? 'syncing' : status,
                schemaId: schema?.id,
            }
        }
    )
}

export interface SearchTermTablesToEnable {
    schemaIds: string[]
    buttonLabel: string
}

/** The disabled search term tables this account needs, with a button label that names them. */
export function searchTermTablesToEnable(source: ExternalDataSource, channelTypes: string[]): SearchTermTablesToEnable {
    const tables = searchTermTables(source, channelTypes).filter(
        ({ state, schemaId }) => state === 'disabled' && !!schemaId
    )
    return {
        schemaIds: tables.map(({ schemaId }) => schemaId!),
        buttonLabel:
            tables.length === 0 ? '' : tables.length === 1 ? `Enable ${tables[0].label}` : 'Enable search terms tables',
    }
}

function searchTermsNotice(source: ExternalDataSource, channelTypes: string[] | undefined): SearchNotice | null {
    if (!channelTypes) {
        return null
    }
    const tables = searchTermTables(source, channelTypes)
    if (tables.length === 0) {
        return {
            message: 'Search terms come from Search and Performance Max campaigns. This account has none.',
            kind: 'info',
        }
    }
    const issues = tables.flatMap(({ label, campaigns, state }) => {
        const message = {
            missing: `The ${label} for ${campaigns} campaigns isn't in this source yet. Click "Pull new schemas" in the source settings to add it.`,
            disabled: `Enable the ${label} to see search terms from ${campaigns} campaigns. Enabling it syncs the table's full history.`,
            syncing: `The ${label} is syncing. Search terms from ${campaigns} campaigns will appear when the first sync finishes.`,
            failed: `The ${label} failed to sync. Retry it in the source settings.`,
            billing: `A billing limit is blocking the ${label} sync. Check the source settings.`,
            paused: `The ${label} sync has stopped. Resume it in the source settings.`,
            stale: `The ${label} is out of date. Sync it again in the source settings.`,
            ready: '',
            empty: '',
        }[state]
        return message ? [{ message, state }] : []
    })
    return issues.length > 0
        ? {
              message: issues.map(({ message }) => message).join('\n'),
              kind: noticeKind(issues.map(({ state }) => state)),
          }
        : null
}

/** Names a source the way the marketing dashboard does: its prefix, or the platform and a short id. */
export function searchSourceName(source: ExternalDataSource): string {
    const label = SEARCH_PLATFORM_LABELS[source.source_type as SearchPlatform] ?? source.source_type
    return source.prefix || `${label} (${source.id.slice(0, 8)})`
}

export function searchPerformanceSource(
    source: ExternalDataSource,
    breakdown: SearchBreakdown = 'keyword',
    detail = false
): MarketingAnalyticsSearchSource | null {
    if (source.source_type === 'GoogleAds' && breakdown === 'search_term') {
        return googleSearchTermsSource(source)
    }
    const table = (name: string): string | undefined => readyTable(source, name)
    const tables = searchTableNames(source, breakdown, detail).map(table)
    if (source.source_type === 'GoogleSearchConsole') {
        return tables[0] ? { sourceType: 'GoogleSearchConsole', statsTable: tables[0], queryPageTable: detail } : null
    }
    if (tables.length === 0 || tables.some((table) => !table)) {
        return null
    }
    return source.source_type === 'GoogleAds'
        ? {
              sourceType: 'GoogleAds',
              statsTable: tables[tables.length - 1]!,
              ...(breakdown === 'keyword'
                  ? {
                        keywordTable: tables[0],
                        ...(table('keyword_placement_stats')
                            ? { placementTable: table('keyword_placement_stats') }
                            : {}),
                    }
                  : {}),
          }
        : { sourceType: 'BingAds', statsTable: tables[0]! }
}

export function searchPerformanceSourceNotice(
    source: ExternalDataSource,
    breakdown: SearchBreakdown = 'keyword',
    detail = false,
    channelTypes?: string[]
): SearchNotice | null {
    if (breakdown === 'search_term' && source.source_type === 'BingAds') {
        return null
    }
    if (breakdown === 'search_term' && source.source_type === 'GoogleAds' && readyTable(source, 'campaign')) {
        return searchTermsNotice(source, channelTypes)
    }
    const querySource = searchPerformanceSource(source, breakdown, detail)
    if (querySource) {
        if (source.source_type === 'GoogleAds' && breakdown === 'keyword' && !querySource.placementTable) {
            const status = searchTableStatus(source.schemas.find((schema) => schema.name === 'keyword_placement_stats'))
            const message = {
                disabled: 'Enable keyword_placement_stats in the source settings to see Top and First percentages.',
                pending: 'Position data will appear after the first sync of keyword_placement_stats finishes.',
                failed: 'The sync of keyword_placement_stats failed. Retry it in the source settings to see position data.',
                billing:
                    'A billing limit is blocking keyword_placement_stats. Check the source settings to restore position data.',
                paused: 'Syncing has stopped for keyword_placement_stats. Resume it in the source settings to restore position data.',
                stale: 'Position data in keyword_placement_stats is out of date. Sync it again in the source settings.',
                ready: '',
                empty: '',
            }[status]
            return message ? { message: `${message} Traffic data is available.`, kind: noticeKind([status]) } : null
        }
        return null
    }
    const names = searchTableNames(source, breakdown, detail)
    const tablesByStatus = new Map<Exclude<SearchTableStatus, 'ready' | 'empty'>, string[]>()
    for (const name of names) {
        const status = searchTableStatus(source.schemas.find((schema) => schema.name === name))
        if (status !== 'ready' && status !== 'empty') {
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
    if (issues.length === 0) {
        return null
    }
    return {
        message: `${issues.join(' ')} Data from this source will appear when the tables are ready.`,
        kind: noticeKind([...tablesByStatus.keys()]),
    }
}

export const SEARCH_SOURCE_TYPES = ['GoogleAds', 'BingAds', 'GoogleSearchConsole']

export function selectedSearchSources(
    sources: ExternalDataSource[],
    selectedIds: string[],
    types: string[] = SEARCH_SOURCE_TYPES
): ExternalDataSource[] {
    const searchSources = sources.filter((source) => types.includes(source.source_type))
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
