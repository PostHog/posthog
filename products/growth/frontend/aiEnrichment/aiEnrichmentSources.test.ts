import { AIEnrichmentSource } from './aiEnrichmentLogic'
import { sourcesDisabledReason } from './aiEnrichmentSources'

const fetchSource = (overrides: Partial<AIEnrichmentSource> = {}): AIEnrichmentSource => ({
    key: 'pricing',
    kind: 'fetch',
    url: 'https://{domain}/pricing',
    ...overrides,
})

const searchSource = (overrides: Partial<AIEnrichmentSource> = {}): AIEnrichmentSource => ({
    key: 'ai_news',
    kind: 'search',
    query: '"{name}" AI OR LLM product',
    ...overrides,
})

describe('aiEnrichmentSources', () => {
    it('allows an empty list', () => {
        expect(sourcesDisabledReason([])).toBeUndefined()
    })

    it.each([
        ['empty key', [fetchSource({ key: '' })], 'Add a key for every web source'],
        ['fetch source missing a url', [fetchSource({ url: '' })], 'Add a URL for every fetch source'],
        ['search source missing a query', [searchSource({ query: '' })], 'Add a query for every search source'],
        ['duplicate keys', [fetchSource(), searchSource({ key: 'pricing' })], 'Web source keys must be unique'],
    ])('%s disables with a reason', (_label, sources, expected) => {
        expect(sourcesDisabledReason(sources)).toBe(expected)
    })

    it('allows a fully specified list', () => {
        expect(sourcesDisabledReason([fetchSource(), searchSource()])).toBeUndefined()
    })
})
