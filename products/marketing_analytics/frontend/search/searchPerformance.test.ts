import { dayjs } from 'lib/dayjs'

import { ExternalDataSchemaStatus, ExternalDataSource, ExternalDataSourceSchema } from '~/types'

import { searchPerformanceSource, searchPerformanceSourceNotice, selectedSearchSources } from './searchPerformance'

const schema = (name: string, shouldSync = true, synced = true): ExternalDataSourceSchema =>
    ({
        name,
        should_sync: shouldSync,
        sync_frequency: '24hour',
        last_synced_at: synced ? dayjs('2025-02-14T12:00:00Z') : undefined,
        table: synced ? { name: `example_${name}`, hogql_name: `example.${name}` } : undefined,
    }) as ExternalDataSourceSchema

describe('search performance sources', () => {
    beforeEach(() => jest.useFakeTimers().setSystemTime(new Date('2025-02-15T12:00:00Z')))
    afterEach(() => jest.useRealTimers())
    it.each([
        [
            'GoogleAds',
            [schema('keyword'), schema('keyword_stats')],
            { sourceType: 'GoogleAds', keywordTable: 'example.keyword', statsTable: 'example.keyword_stats' },
        ],
        ['GoogleAds', [schema('keyword'), schema('keyword_stats', false)], null],
        ['GoogleAds', [schema('keyword', true, false), schema('keyword_stats')], null],
        ['GoogleAds', [schema('search_term_stats')], null],
        [
            'BingAds',
            [schema('keyword_performance_report')],
            { sourceType: 'BingAds', statsTable: 'example.keyword_performance_report' },
        ],
        ['BingAds', [schema('keyword_performance_report', false)], null],
        [
            'GoogleSearchConsole',
            [schema('search_analytics_by_query')],
            {
                sourceType: 'GoogleSearchConsole',
                statsTable: 'example.search_analytics_by_query',
                queryPageTable: false,
            },
        ],
        [
            'GoogleSearchConsole',
            [schema('search_analytics_by_query', false), schema('search_analytics_by_query_page')],
            {
                sourceType: 'GoogleSearchConsole',
                statsTable: 'example.search_analytics_by_query_page',
                queryPageTable: true,
            },
        ],
        ['GoogleSearchConsole', [schema('search_analytics_by_query_page', true, false)], null],
    ])('requires synced keyword tables for %s', (source_type, schemas, expected) => {
        expect(searchPerformanceSource({ source_type, schemas } as ExternalDataSource)).toEqual(expected)
    })

    it.each([
        ['GoogleAds', ['landing_page_stats'], 'page', false, 'example.landing_page_stats'],
        ['BingAds', ['keyword_performance_report'], 'page', false, undefined],
        [
            'BingAds',
            ['destination_url_performance_report'],
            'page',
            false,
            'example.destination_url_performance_report',
        ],
        [
            'GoogleSearchConsole',
            ['search_analytics_by_page', 'search_analytics_by_query_page'],
            'page',
            false,
            'example.search_analytics_by_page',
        ],
        [
            'GoogleSearchConsole',
            ['search_analytics_by_query', 'search_analytics_by_query_page'],
            'keyword',
            true,
            'example.search_analytics_by_query_page',
        ],
        ['GoogleSearchConsole', ['search_analytics_by_query'], 'keyword', true, undefined],
    ] as const)('uses the right table for %s %s %s details=%s', (source_type, schemas, breakdown, detail, expected) => {
        expect(
            searchPerformanceSource(
                { source_type, schemas: schemas.map((name) => schema(name)) } as ExternalDataSource,
                breakdown,
                detail
            )?.statsTable
        ).toEqual(expected)
    })

    it.each([
        ['disabled', { should_sync: false }, 'Enable keyword_stats'],
        ['first sync with a materialized table', { last_synced_at: undefined }, 'first sync'],
        ['failed', { status: ExternalDataSchemaStatus.Failed }, 'failed'],
        ['paused', { status: ExternalDataSchemaStatus.Paused }, 'Syncing has stopped'],
        ['billing limit', { status: 'Billing limits' as ExternalDataSchemaStatus }, 'billing limit'],
        ['stale', { last_synced_at: dayjs('2025-02-10T12:00:00Z') }, 'out of date'],
    ])('excludes %s tables and explains how to fix them', (_, overrides, message) => {
        const source = {
            source_type: 'GoogleAds',
            schemas: [schema('keyword'), { ...schema('keyword_stats'), ...overrides }],
        } as ExternalDataSource
        expect(searchPerformanceSource(source)).toBeNull()
        expect(searchPerformanceSourceNotice(source)).toContain(message)
    })

    it.each(['keyword', 'page'] as const)('uses fresh query-page data instead of a stale %s aggregate', (breakdown) => {
        const source = {
            source_type: 'GoogleSearchConsole',
            schemas: [
                { ...schema('search_analytics_by_query'), last_synced_at: dayjs('2025-02-10T12:00:00Z') },
                { ...schema('search_analytics_by_page'), last_synced_at: dayjs('2025-02-10T12:00:00Z') },
                schema('search_analytics_by_query_page'),
            ],
        } as ExternalDataSource
        expect(searchPerformanceSource(source, breakdown)).toEqual({
            sourceType: 'GoogleSearchConsole',
            statsTable: 'example.search_analytics_by_query_page',
            queryPageTable: true,
        })
        expect(searchPerformanceSourceNotice(source, breakdown)).toContain('Showing query-and-page data instead')
        expect(searchPerformanceSourceNotice(source, breakdown)).toContain('Totals may differ')
        source.schemas[2].last_synced_at = dayjs('2025-02-10T12:00:00Z')
        expect(searchPerformanceSource(source, breakdown)).toBeNull()
        expect(searchPerformanceSource(source, breakdown, true)).toBeNull()
        expect(searchPerformanceSourceNotice(source, breakdown, true)).toContain('out of date')
    })

    it.each([
        ['24hour', '2025-02-13T12:00:00Z', true],
        ['24hour', '2025-02-13T11:59:59Z', false],
        ['7day', '2025-02-10T12:00:00Z', true],
        ['1hour', '2025-02-15T09:00:00Z', false],
        ['15min', '2025-02-15T11:29:00Z', false],
        [undefined, '2025-02-10T12:00:00Z', true],
    ])('uses each table cadence (%s) when the last successful sync is %s', (syncFrequency, lastSync, ready) => {
        const source = {
            source_type: 'BingAds',
            schemas: [
                {
                    ...schema('keyword_performance_report'),
                    sync_frequency: syncFrequency,
                    last_synced_at: dayjs(lastSync),
                    status: ExternalDataSchemaStatus.Running,
                },
            ],
        } as ExternalDataSource
        expect(searchPerformanceSource(source) !== null).toBe(ready)
        expect(searchPerformanceSourceNotice(source) === null).toBe(ready)
    })

    it.each([
        [[], ['google-main', 'google-secondary', 'bing']],
        [['google-secondary'], ['google-secondary']],
        [
            ['google-main', 'bing'],
            ['google-main', 'bing'],
        ],
        [['meta'], []],
        [['meta', 'bing'], ['bing']],
    ])('selects connected search accounts for %j', (selectedIds, expectedIds) => {
        const sources = [
            { id: 'google-main', source_type: 'GoogleAds' },
            { id: 'google-secondary', source_type: 'GoogleAds' },
            { id: 'bing', source_type: 'BingAds' },
            { id: 'meta', source_type: 'MetaAds' },
        ] as ExternalDataSource[]
        expect(selectedSearchSources(sources, selectedIds).map((source) => source.id)).toEqual(expectedIds)
    })
})
