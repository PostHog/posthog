import { describe, expect, it } from 'vitest'

import { Searcher, type SearchDoc } from '../src/lib/searcher'

const docs: SearchDoc[] = [
    {
        id: 'op:petsList',
        kind: 'operation',
        name: 'petsList',
        description: 'Returns all pets in the project, paginated.',
        summary: 'List all pets',
        snippet: 'GET /api/pets/ — List all pets',
    },
    {
        id: 'op:petsCreate',
        kind: 'operation',
        name: 'petsCreate',
        description: 'Adds a new pet.',
        summary: 'Create a pet',
        snippet: 'POST /api/pets/ — Create a pet',
    },
    {
        id: 'op:petsRetrieve',
        kind: 'operation',
        name: 'petsRetrieve',
        description: 'Returns a single pet.',
        summary: 'Get a pet by ID',
        snippet: 'GET /api/pets/{id}/ — Get a pet by ID',
    },
    {
        id: 'type:Pet',
        kind: 'type',
        name: 'Pet',
        description: 'A pet with a name and optional tag.',
        summary: 'A pet with a name and optional tag.',
        snippet: 'Schemas.Pet — A pet with a name and optional tag.',
    },
]

describe('Searcher', () => {
    it('ranks natural-language queries by description match', () => {
        const searcher = new Searcher(docs)
        const result = searcher.search({ query: 'list all pets' })
        expect(result.hits[0]?.name).toBe('petsList')
    })

    it('returns the full index when the query is empty', () => {
        const searcher = new Searcher(docs)
        const result = searcher.search({})
        expect(result.total).toBe(docs.length)
        expect(result.hits.map((h) => h.name)).toEqual(docs.map((d) => d.name).sort())
    })

    it('paginates correctly', () => {
        const searcher = new Searcher(docs)
        const page1 = searcher.search({ pageSize: 2, page: 1 })
        const page2 = searcher.search({ pageSize: 2, page: 2 })
        expect(page1.hits.length).toBe(2)
        expect(page2.hits.length).toBe(2)
        expect(page1.hits[0]?.name).not.toBe(page2.hits[0]?.name)
    })

    it('caps pageSize at 100', () => {
        const searcher = new Searcher(docs)
        const result = searcher.search({ pageSize: 500 })
        expect(result.pageSize).toBe(100)
    })

    it('filters by kind', () => {
        const searcher = new Searcher(docs)
        const types = searcher.search({ kind: 'type' })
        expect(types.hits.every((h) => h.kind === 'type')).toBe(true)
        const ops = searcher.search({ kind: 'operation' })
        expect(ops.hits.every((h) => h.kind === 'operation')).toBe(true)
    })
})
