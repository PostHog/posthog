import { ExternalDataSource, ExternalDataSourceSchema } from '~/types'

import { searchPerformanceSource, selectedSearchSources } from './searchPerformance'

const schema = (name: string, shouldSync = true, synced = true): ExternalDataSourceSchema =>
    ({
        name,
        should_sync: shouldSync,
        table: synced ? { name: `example_${name}`, hogql_name: `example.${name}` } : undefined,
    }) as ExternalDataSourceSchema

describe('search performance sources', () => {
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
