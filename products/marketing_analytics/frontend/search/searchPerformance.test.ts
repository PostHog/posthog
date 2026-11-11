import { dayjs } from 'lib/dayjs'

import { ExternalDataSchemaStatus, ExternalDataSource, ExternalDataSourceSchema } from '~/types'

import {
    searchPerformanceSource,
    searchPerformanceSourceNotice,
    searchTermTablesToEnable,
    selectedSearchSources,
} from './searchPerformance'

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
        [
            'GoogleAds',
            [schema('keyword'), schema('keyword_stats'), schema('keyword_placement_stats')],
            {
                sourceType: 'GoogleAds',
                keywordTable: 'example.keyword',
                statsTable: 'example.keyword_stats',
                placementTable: 'example.keyword_placement_stats',
            },
        ],
        [
            'GoogleAds',
            [schema('keyword'), schema('keyword_stats'), schema('keyword_placement_stats', false)],
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
            null,
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
        ['GoogleSearchConsole', ['search_analytics_by_query_page'], 'keyword', false, undefined],
        ['GoogleSearchConsole', ['search_analytics_by_query_page'], 'page', false, undefined],
    ] as const)('uses the right table for %s %s %s details=%s', (source_type, schemas, breakdown, detail, expected) => {
        expect(
            searchPerformanceSource(
                { source_type, schemas: schemas.map((name) => schema(name)) } as ExternalDataSource,
                breakdown,
                detail
            )?.statsTable
        ).toEqual(expected)
    })

    const notice = (message: string, kind: string): object => ({ message: expect.stringContaining(message), kind })

    it.each([
        ['disabled', { should_sync: false }, notice('Enable keyword_stats', 'attention')],
        ['first sync with a materialized table', { last_synced_at: undefined }, notice('first sync', 'syncing')],
        ['failed', { status: ExternalDataSchemaStatus.Failed }, notice('failed', 'attention')],
        ['paused', { status: ExternalDataSchemaStatus.Paused }, notice('Syncing has stopped', 'attention')],
        [
            'billing limit',
            { status: 'Billing limits' as ExternalDataSchemaStatus },
            notice('billing limit', 'attention'),
        ],
        ['stale', { last_synced_at: dayjs('2025-02-10T12:00:00Z') }, notice('out of date', 'attention')],
        ['synced with no rows', { table: undefined, status: ExternalDataSchemaStatus.Completed }, null],
    ])('excludes %s tables and explains how to fix them', (_, overrides, expected) => {
        const source = {
            source_type: 'GoogleAds',
            schemas: [schema('keyword'), { ...schema('keyword_stats'), ...overrides }],
        } as ExternalDataSource
        expect(searchPerformanceSource(source)).toBeNull()
        expect(searchPerformanceSourceNotice(source)).toEqual(expected)
    })

    it.each([
        ['disabled', { should_sync: false }, 'Enable keyword_placement_stats'],
        ['pending', { last_synced_at: undefined }, 'first sync of keyword_placement_stats'],
        ['failed', { status: ExternalDataSchemaStatus.Failed }, 'failed'],
        ['paused', { status: ExternalDataSchemaStatus.Paused }, 'Resume it'],
        ['billing', { status: 'Billing limits' as ExternalDataSchemaStatus }, 'billing limit'],
        ['stale', { last_synced_at: dayjs('2025-02-10T12:00:00Z') }, 'out of date'],
    ])('keeps traffic available when placement is %s', (_, overrides, message) => {
        const source = {
            source_type: 'GoogleAds',
            schemas: [
                schema('keyword'),
                schema('keyword_stats'),
                { ...schema('keyword_placement_stats'), ...overrides },
                schema('landing_page_stats'),
            ],
        } as ExternalDataSource
        expect(searchPerformanceSource(source)).toEqual({
            sourceType: 'GoogleAds',
            keywordTable: 'example.keyword',
            statsTable: 'example.keyword_stats',
        })
        expect(searchPerformanceSourceNotice(source)?.message).toContain(message)
        expect(searchPerformanceSourceNotice(source)?.message).toContain('Traffic data is available.')
        expect(searchPerformanceSourceNotice(source, 'page')).toBeNull()
        source.schemas[2] = schema('keyword_placement_stats')
        expect(searchPerformanceSourceNotice(source)).toBeNull()
    })

    it.each([
        [
            'Search only',
            [schema('campaign'), schema('search_term_stats')],
            { sourceType: 'GoogleAds', statsTable: 'example.campaign', searchTermTable: 'example.search_term_stats' },
        ],
        [
            'Performance Max only',
            [schema('campaign'), schema('performance_max_search_term_stats')],
            {
                sourceType: 'GoogleAds',
                statsTable: 'example.campaign',
                performanceMaxSearchTermTable: 'example.performance_max_search_term_stats',
            },
        ],
        [
            'mixed',
            [schema('campaign'), schema('search_term_stats'), schema('performance_max_search_term_stats')],
            {
                sourceType: 'GoogleAds',
                statsTable: 'example.campaign',
                searchTermTable: 'example.search_term_stats',
                performanceMaxSearchTermTable: 'example.performance_max_search_term_stats',
            },
        ],
        [
            'mixed with Performance Max syncing',
            [schema('campaign'), schema('search_term_stats'), schema('performance_max_search_term_stats', true, false)],
            { sourceType: 'GoogleAds', statsTable: 'example.campaign', searchTermTable: 'example.search_term_stats' },
        ],
        ['no ready search term table', [schema('campaign'), schema('search_term_stats', false)], null],
        ['no ready campaign table', [schema('campaign', false), schema('search_term_stats')], null],
    ])('queries the ready search term tables for a %s account', (_, schemas, expected) => {
        const source = { source_type: 'GoogleAds', schemas } as ExternalDataSource
        expect(searchPerformanceSource(source, 'search_term')).toEqual(expected)
    })

    it.each([
        ['missing', undefined, expect.stringContaining('Pull new schemas'), [], ''],
        [
            'disabled',
            { should_sync: false },
            expect.stringContaining('Enable the Performance Max search terms table'),
            ['pmax-id'],
            'Enable Performance Max search terms table',
        ],
        [
            'syncing',
            { last_synced_at: undefined },
            expect.stringContaining('The Performance Max search terms table is syncing'),
            [],
            '',
        ],
        ['ready', {}, null, [], ''],
        ['synced with no rows', { table: undefined, status: ExternalDataSchemaStatus.Completed }, null, [], ''],
    ])(
        'asks only for the tables an account needs when the Performance Max table is %s',
        (_, overrides, message, enableSchemaIds, buttonLabel) => {
            const schemas = [schema('campaign'), schema('search_term_stats', false)]
            if (overrides) {
                schemas.push({ ...schema('performance_max_search_term_stats'), id: 'pmax-id', ...overrides })
            }
            const source = { source_type: 'GoogleAds', schemas } as ExternalDataSource
            const notice = searchPerformanceSourceNotice(source, 'search_term', false, ['PERFORMANCE_MAX', 'DISPLAY'])
            expect(notice?.message ?? null).toEqual(message)
            expect(notice?.message ?? '').not.toMatch(/search_term_stats/)
            expect(searchTermTablesToEnable(source, ['PERFORMANCE_MAX', 'DISPLAY'])).toEqual({
                schemaIds: enableSchemaIds,
                buttonLabel,
            })
        }
    )

    it.each([
        ['an unknown campaign mix', undefined, null],
        [
            'Search and Performance Max campaigns',
            ['SEARCH', 'PERFORMANCE_MAX'],
            "Enable the search terms table to see search terms from Search campaigns. Enabling it syncs the table's full history.\n" +
                'The Performance Max search terms table for Performance Max campaigns isn\'t in this source yet. Click "Pull new schemas" in the source settings to add it.',
        ],
        ['no Search or Performance Max campaigns', ['DISPLAY'], expect.stringContaining('This account has none.')],
    ])('explains search terms for %s', (_, channelTypes, message) => {
        const source = {
            source_type: 'GoogleAds',
            schemas: [schema('campaign'), schema('search_term_stats', false)],
        } as ExternalDataSource
        const notice = searchPerformanceSourceNotice(source, 'search_term', false, channelTypes)
        expect(notice?.message ?? null).toEqual(message)
    })

    it.each(['keyword', 'page'] as const)(
        'keeps %s metrics unavailable when its dedicated table is stale',
        (breakdown) => {
            const source = {
                source_type: 'GoogleSearchConsole',
                schemas: [
                    { ...schema('search_analytics_by_query'), last_synced_at: dayjs('2025-02-10T12:00:00Z') },
                    { ...schema('search_analytics_by_page'), last_synced_at: dayjs('2025-02-10T12:00:00Z') },
                    schema('search_analytics_by_query_page'),
                ],
            } as ExternalDataSource
            expect(searchPerformanceSource(source, breakdown)).toBeNull()
            expect(searchPerformanceSourceNotice(source, breakdown)?.message).toContain('out of date')
            expect(searchPerformanceSource(source, breakdown, true)).toEqual({
                sourceType: 'GoogleSearchConsole',
                statsTable: 'example.search_analytics_by_query_page',
                queryPageTable: true,
            })
            source.schemas[2].last_synced_at = dayjs('2025-02-10T12:00:00Z')
            expect(searchPerformanceSource(source, breakdown)).toBeNull()
            expect(searchPerformanceSource(source, breakdown, true)).toBeNull()
            expect(searchPerformanceSourceNotice(source, breakdown, true)?.message).toContain('out of date')
        }
    )

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
