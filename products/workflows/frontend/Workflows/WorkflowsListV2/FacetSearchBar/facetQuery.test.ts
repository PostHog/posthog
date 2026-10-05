import {
    FacetDefinition,
    FacetSearchValue,
    countFacetValues,
    matchesFacetQuery,
    parseFacetQuery,
    serializeFacetQuery,
} from './facetQuery'

interface Item {
    name: string
    status: string
    subjects: string[]
    senders: string[]
}

const FACETS: FacetDefinition<Item>[] = [
    { key: 'status', label: 'Status', description: 'Lifecycle', getValues: (item) => [item.status] },
    {
        key: 'sends',
        aliases: ['subject'],
        label: 'Sends',
        description: 'Email subject',
        getValues: (item) => item.subjects,
    },
    { key: 'from', label: 'From', description: 'Sender', getValues: (item) => item.senders },
]

const ITEMS: Item[] = [
    { name: 'Welcome', status: 'active', subjects: ['Hi there', 'Your trial ends'], senders: ['a@example.com'] },
    { name: 'Renewal', status: 'draft', subjects: ['Renew now'], senders: ['b@example.com'] },
    { name: 'Sync', status: 'draft', subjects: [], senders: [] },
    { name: 'Promo', status: 'archived', subjects: ['Deals'], senders: ['a@example.com', 'b@example.com'] },
]

const matchesText = (item: Item, text: string): boolean => item.name.toLowerCase().includes(text.toLowerCase())

const names = (value: FacetSearchValue): string[] =>
    ITEMS.filter((item) => matchesFacetQuery(item, value, FACETS, matchesText)).map((item) => item.name)

describe('facetQuery', () => {
    it.each([
        ['status:active', [{ facet: 'status', value: 'active', negated: false }]],
        ['-status:archived', [{ facet: 'status', value: 'archived', negated: true }]],
        ['sends:"Your trial ends"', [{ facet: 'sends', value: 'Your trial ends', negated: false }]],
        ['subject:Deals', [{ facet: 'sends', value: 'Deals', negated: false }]],
        ['sends:"Say \\"hi\\""', [{ facet: 'sends', value: 'Say "hi"', negated: false }]],
        ['nope:x status:draft', [{ facet: 'status', value: 'draft', negated: false }]],
        ['status: status:""', []],
        ['STATUS:active', [{ facet: 'status', value: 'active', negated: false }]],
    ])('parses %s', (query, filters) => {
        expect(parseFacetQuery(query, FACETS)).toEqual(filters)
    })

    it.each([
        'status:active',
        '-status:archived status:draft',
        'sends:"Your trial ends"',
        'sends:"Say \\"hi\\""',
        'from:a@example.com -sends:Deals',
    ])('round-trips %s', (query) => {
        const filters = parseFacetQuery(query, FACETS)
        expect(serializeFacetQuery(filters)).toEqual(query)
        expect(parseFacetQuery(serializeFacetQuery(filters), FACETS)).toEqual(filters)
    })

    it('serializes an alias to the canonical key', () => {
        expect(serializeFacetQuery(parseFacetQuery('subject:Deals', FACETS))).toEqual('sends:Deals')
    })

    it.each<[string, FacetSearchValue, string[]]>([
        ['no filters', { filters: [], text: '' }, ['Welcome', 'Renewal', 'Sync', 'Promo']],
        [
            'OR within a facet',
            {
                filters: [
                    { facet: 'status', value: 'active', negated: false },
                    { facet: 'status', value: 'archived', negated: false },
                ],
                text: '',
            },
            ['Welcome', 'Promo'],
        ],
        [
            'AND across facets',
            {
                filters: [
                    { facet: 'status', value: 'draft', negated: false },
                    { facet: 'from', value: 'b@example.com', negated: false },
                ],
                text: '',
            },
            ['Renewal'],
        ],
        [
            'negation excludes, and an item with no values passes it',
            { filters: [{ facet: 'from', value: 'a@example.com', negated: true }], text: '' },
            ['Renewal', 'Sync'],
        ],
        [
            'an item with no values fails a positive pill',
            { filters: [{ facet: 'sends', value: 'Renew now', negated: false }], text: '' },
            ['Renewal'],
        ],
        [
            'a value on any of several steps matches, case-insensitively',
            { filters: [{ facet: 'sends', value: 'your TRIAL ends', negated: false }], text: '' },
            ['Welcome'],
        ],
        [
            'text is AND with the pills',
            { filters: [{ facet: 'status', value: 'draft', negated: false }], text: 'syn' },
            ['Sync'],
        ],
    ])('matches: %s', (_, value, expected) => {
        expect(names(value)).toEqual(expected)
    })

    it('counts values ignoring the same facet pills but respecting other facets and the text', () => {
        const value: FacetSearchValue = {
            filters: [
                { facet: 'status', value: 'draft', negated: false },
                { facet: 'from', value: 'b@example.com', negated: false },
            ],
            text: '',
        }
        expect(countFacetValues(ITEMS, 'status', value, FACETS, matchesText)).toEqual([
            { value: 'archived', count: 1 },
            { value: 'draft', count: 1 },
        ])
        expect(countFacetValues(ITEMS, 'from', value, FACETS, matchesText)).toEqual([
            { value: 'b@example.com', count: 1 },
        ])
        expect(countFacetValues(ITEMS, 'status', { filters: [], text: 'e' }, FACETS, matchesText)).toEqual([
            { value: 'active', count: 1 },
            { value: 'draft', count: 1 },
        ])
        expect(countFacetValues(ITEMS, 'status', { filters: [], text: '' }, FACETS, matchesText)[0]).toEqual({
            value: 'draft',
            count: 2,
        })
    })
})
