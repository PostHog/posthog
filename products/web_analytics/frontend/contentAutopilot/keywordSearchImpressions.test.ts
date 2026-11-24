import { buildKeywordImpressionsQuery, findSearchConsoleQueryTable } from './keywordSearchImpressions'

describe('keywordSearchImpressions', () => {
    it.each([
        [
            'the per-search table, not the per-page one that repeats a search for every page',
            ['googlesearchconsole.search_analytics_by_query_page', 'googlesearchconsole.search_analytics_by_query'],
            'googlesearchconsole.search_analytics_by_query',
        ],
        [
            'a source created with a prefix',
            ['googlesearchconsole.blog.search_analytics_by_query', 'stripe.charges'],
            'googlesearchconsole.blog.search_analytics_by_query',
        ],
        [
            'the dotted name over the legacy underscore one',
            ['googlesearchconsole_search_analytics_by_query', 'googlesearchconsole.search_analytics_by_query'],
            'googlesearchconsole.search_analytics_by_query',
        ],
        ['nothing without a Search Console source', ['stripe.charges', 'search_analytics_by_query_image'], null],
    ])('finds %s', (_, names, expected) => {
        expect(findSearchConsoleQueryTable(names.map((name) => ({ name })))).toBe(expected)
    })

    it('escapes keywords and reads the window, so a quote in a keyword cannot change the query', () => {
        const query = buildKeywordImpressionsQuery(
            'googlesearchconsole.search_analytics_by_query',
            ["Don't Track", 'pricing'],
            { from: '2026-10-01', to: '2026-10-07' }
        )

        expect(query).toContain("['don\\'t track', 'pricing']")
        expect(query).toContain("toDate(date) >= toDate('2026-10-01') AND toDate(date) <= toDate('2026-10-07')")
        expect(query).toContain('FROM googlesearchconsole.search_analytics_by_query')
    })
})
