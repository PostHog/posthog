import { AIEnrichmentSource } from './aiEnrichmentLogic'
import { AIEnrichmentOutputField } from './aiEnrichmentOutputFields'
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

const verdictField: AIEnrichmentOutputField = { key: 'verdict', type: 'boolean', description: '' }
const evidenceUrlField: AIEnrichmentOutputField = { key: 'evidence_url', type: 'string', description: '' }

describe('aiEnrichmentSources', () => {
    it('allows an empty list regardless of output fields', () => {
        expect(sourcesDisabledReason([], [])).toBeUndefined()
        expect(sourcesDisabledReason([], [verdictField])).toBeUndefined()
    })

    it.each([
        ['empty key', [fetchSource({ key: '' })], 'Add a key for every web source'],
        ['fetch source missing a url', [fetchSource({ url: '' })], 'Add a URL for every fetch source'],
        ['search source missing a query', [searchSource({ query: '' })], 'Add a query for every search source'],
        ['duplicate keys', [fetchSource(), searchSource({ key: 'pricing' })], 'Web source keys must be unique'],
    ])('%s disables with a reason', (_label, sources, expected) => {
        expect(sourcesDisabledReason(sources, [evidenceUrlField])).toBe(expected)
    })

    it("requires a string 'evidence_url' output field once a source is added", () => {
        expect(sourcesDisabledReason([fetchSource()], [])).toBe(
            "Add a string 'evidence_url' output field to use web sources"
        )
        expect(sourcesDisabledReason([fetchSource()], [verdictField])).toBe(
            "Add a string 'evidence_url' output field to use web sources"
        )
        expect(sourcesDisabledReason([fetchSource()], [{ ...evidenceUrlField, type: 'number' }])).toBe(
            "Add a string 'evidence_url' output field to use web sources"
        )
    })

    it('allows a fully specified list with a matching evidence_url output field', () => {
        expect(sourcesDisabledReason([fetchSource(), searchSource()], [verdictField, evidenceUrlField])).toBeUndefined()
    })
})
