import posthog from 'posthog-js'

import { initKeaTests } from '~/test/init'

import { FacetDefinition, FacetSearchValue } from './facetQuery'
import { facetSearchBarLogic } from './facetSearchBarLogic'

interface Item {
    name: string
    status: string
    subjects: string[]
}

const FACETS: FacetDefinition<Item>[] = [
    {
        key: 'status',
        label: 'Status',
        description: 'Lifecycle',
        showOnFocus: true,
        order: 1,
        getValues: (item) => [item.status],
        normalizeValue: (value) => value.toLowerCase(),
        formatValue: (value) => value[0].toUpperCase() + value.slice(1),
    },
    {
        key: 'sends',
        aliases: ['subject'],
        label: 'Sends',
        description: 'Email subject',
        freeTextValues: true,
        showOnFocus: true,
        order: 2,
        getValues: (item) => item.subjects,
    },
    {
        key: 'stageName',
        aliases: ['phase'],
        label: 'Stage',
        description: 'Found by typing',
        order: 3,
        getValues: () => ['one'],
        resolveValue: (value) => (value === 'first' ? 'one' : value),
    },
    {
        key: 'health',
        label: 'Health',
        description: 'Known once metrics load',
        order: 4,
        getValues: () => [],
        emptyLabel: 'Health shows once run metrics load',
    },
]

const ITEMS: Item[] = [
    { name: 'Welcome', status: 'active', subjects: ['Start here', 'Status update'] },
    { name: 'Renewal', status: 'draft', subjects: ['Renew now'] },
    { name: 'Sync', status: 'draft', subjects: [] },
    { name: 'Promo', status: 'archived', subjects: ['Deals', 'Deals for you'] },
]

const matchesText = (item: Item, text: string): boolean => item.name.toLowerCase().includes(text.toLowerCase())

describe('facetSearchBarLogic', () => {
    let onChange: jest.Mock
    let logic: ReturnType<typeof facetSearchBarLogic.build>

    const mountWith = (value: FacetSearchValue): void => {
        logic = facetSearchBarLogic({ id: 'test', facets: FACETS, items: ITEMS, value, onChange, matchesText })
        logic.mount()
    }

    beforeEach(() => {
        initKeaTests()
        onChange = jest.fn()
    })

    afterEach(() => logic?.unmount())

    it('lists the on-focus facets for an empty input, in order', () => {
        mountWith({ filters: [], text: '' })
        expect(logic.values.suggestions.map((s) => [s.kind, s.label, s.detail])).toEqual([
            ['facet', 'status:', 'Lifecycle'],
            ['facet', 'sends:', 'Email subject'],
        ])
        expect(logic.values.title).toEqual('Filter by')
    })

    it('offers matching facets, then the search, then values from any facet with counts', () => {
        mountWith({ filters: [], text: '' })
        logic.actions.setInput('sta')
        expect(logic.values.suggestions.map((s) => [s.kind, s.label, s.count])).toEqual([
            ['facet', 'status:', undefined],
            ['facet', 'stageName:', undefined],
            ['search', 'Search for "sta"', undefined],
            ['value', 'Sends: Start here', 1],
            ['value', 'Sends: Status update', 1],
        ])
        expect(logic.values.title).toEqual('Search or filter')
        expect(onChange).toHaveBeenLastCalledWith({ filters: [], text: 'sta' })
    })

    it.each([
        ['the key in another case', 'STAGEN', 'stageName:'],
        ['an alias', 'pha', 'stageName:'],
        ['a negated alias', '-Subj', '-sends:'],
    ])('offers the canonical key for %s', (_, typed, key) => {
        mountWith({ filters: [], text: '' })
        logic.actions.setInput(typed)
        expect(logic.values.suggestions.filter((s) => s.kind === 'facet').map((s) => [s.label, s.nextInput])).toEqual([
            [key, key],
        ])
    })

    it('lists a facet draft values with counts that ignore the facet pills, minus picked values', () => {
        mountWith({
            filters: [{ facet: 'status', value: 'draft', negated: false }],
            text: '',
        })
        logic.actions.setInput('status:')
        expect(logic.values.suggestions.map((s) => [s.kind, s.label, s.count])).toEqual([
            ['value', 'Active', 1],
            ['value', 'Archived', 1],
        ])
        expect(logic.values.title).toEqual('Status')

        logic.actions.setInput('status:arch')
        expect(logic.values.suggestions.map((s) => s.label)).toEqual(['Archived'])
    })

    it('offers "Not" values with how many rows they hide for a negated draft', () => {
        mountWith({ filters: [], text: '' })
        logic.actions.setInput('-status:')
        expect(logic.values.suggestions.map((s) => [s.label, s.detail, s.count])).toEqual([
            ['Not Draft', 'Hides 2', undefined],
            ['Not Active', 'Hides 1', undefined],
            ['Not Archived', 'Hides 1', undefined],
        ])
        expect(logic.values.title).toEqual('Status is not')
    })

    it.each([
        ['a typed value nothing has', [], 'status:zzz', 'No value matches "zzz"'],
        ['a value the search rules out', [], 'syn status:arch', 'No value matches "arch" with your search'],
        ['a free text value nothing has', [], 'sends:zzz', 'No match for "zzz". Press Space to search anyway.'],
        [
            'a free text value other pills rule out',
            [{ facet: 'status', value: 'archived', negated: false }],
            'sends:renew',
            'No match for "renew" with your other filters. Press Space to search anyway.',
        ],
        ['no values left for the search', [], 'zzz sends:', 'No values to pick with your search'],
        [
            'a value that is already a pill',
            [{ facet: 'status', value: 'draft', negated: false }],
            'status:dra',
            'Draft is already a filter',
        ],
        [
            'a value a pill already resolves to',
            [{ facet: 'stageName', value: 'first', negated: false }],
            'stageName:o',
            'one is already a filter',
        ],
        ['a facet whose values have not loaded', [], 'health:', 'Health shows once run metrics load'],
    ])('says why no values are left for %s', (_, filters, input, label) => {
        mountWith({ filters, text: '' })
        logic.actions.setInput(input)
        expect(logic.values.suggestions.map((s) => [s.kind, s.label])).toEqual([['none', label]])
    })

    it.each([
        ['a value', 'status:active', [{ facet: 'status', value: 'active', negated: false }], ''],
        ['a label in another case', 'status:ARCHIVED', [{ facet: 'status', value: 'archived', negated: false }], ''],
        [
            'a negated value after text',
            'wel -status:active',
            [{ facet: 'status', value: 'active', negated: true }],
            'wel ',
        ],
    ])('commits %s that names exactly one option without Space', (_, typed, filters, input) => {
        mountWith({ filters: [], text: '' })
        logic.actions.setInput(typed)
        expect(onChange).toHaveBeenLastCalledWith({ filters, text: input.trim() })
        expect(logic.values.input).toEqual(input)
    })

    it.each([
        ['the start of several values', [], 'status:a'],
        ['a value another value starts with', [], 'sends:deals'],
        ['a value in an open quote', [], 'sends:"Deals for you'],
        ['a value that is already a pill', [{ facet: 'status', value: 'draft', negated: false }], 'status:draft'],
        [
            'a value a pill already resolves to',
            [{ facet: 'stageName', value: 'first', negated: false }],
            'stageName:one',
        ],
    ])('waits for Space on %s', (_, filters, typed) => {
        mountWith({ filters, text: '' })
        logic.actions.setInput(typed)
        expect(onChange).not.toHaveBeenCalled()
        expect(logic.values.input).toEqual(typed)
    })

    it('waits for Space on a value whose caret is not at the end', () => {
        mountWith({ filters: [], text: '' })
        logic.actions.setInput('status:active', 'status:act'.length)
        expect(onChange).not.toHaveBeenCalled()
        expect(logic.values.input).toEqual('status:active')
    })

    it.each([
        ['status:active', ''],
        ['wel status:active', 'wel '],
    ])('drops the space typed right after %s commits', (typed, input) => {
        mountWith({ filters: [], text: '' })
        logic.actions.setInput(typed)
        logic.actions.setInput(`${logic.values.input} `)
        expect(logic.values.input).toEqual(input)
    })

    it('drops a typed token that a pill already resolves to', () => {
        mountWith({ filters: [{ facet: 'stageName', value: 'first', negated: false }], text: '' })
        logic.actions.setInput('stageName:one ')
        expect(onChange).not.toHaveBeenCalled()
        expect(logic.values.input).toEqual('')
    })

    it('stores a typed value in the form the facet keeps', () => {
        mountWith({ filters: [], text: '' })
        logic.actions.setInput('status:Draft ')
        expect(onChange).toHaveBeenLastCalledWith({
            filters: [{ facet: 'status', value: 'draft', negated: false }],
            text: '',
        })
    })

    it.each([
        [
            'picked from the suggestions',
            { filters: [], text: '' },
            () => {
                logic.actions.setInput('status:')
                logic.actions.applyHighlighted()
            },
            { change: 'added', facet: 'status', negated: false, source: 'suggestion' },
        ],
        [
            'typed as a token',
            { filters: [], text: '' },
            () => logic.actions.setInput('-status:draft '),
            { change: 'added', facet: 'status', negated: true, source: 'typed' },
        ],
        [
            'removed with its button',
            { filters: [{ facet: 'status', value: 'draft', negated: false }], text: '' },
            () => logic.actions.removeFilter({ facet: 'status', value: 'draft', negated: false }),
            { change: 'removed', facet: 'status', negated: false, source: 'remove button' },
        ],
        [
            'removed with Backspace',
            { filters: [{ facet: 'sends', value: 'Deals', negated: true }], text: '' },
            () => logic.actions.removeLastFilter(),
            { change: 'removed', facet: 'sends', negated: true, source: 'backspace' },
        ],
    ])('reports a pill %s', (_, value, act, properties) => {
        const capture = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
        mountWith(value)
        act()
        expect(capture.mock.calls).toEqual([['search bar filter changed', { search_bar: 'test', ...properties }]])
        capture.mockRestore()
    })

    it('adds a pill from a value row and keeps the text before the draft', () => {
        mountWith({ filters: [], text: '' })
        logic.actions.setInput('wel status:')
        logic.actions.moveHighlight(1)
        logic.actions.applyHighlighted()
        expect(onChange).toHaveBeenLastCalledWith({
            filters: [{ facet: 'status', value: 'active', negated: false }],
            text: 'wel',
        })
        expect(logic.values.input).toEqual('wel ')
    })

    it.each([
        ['status:zzz', 0, ['↑↓ to move', 'Esc to close']],
        ['', 0, ['Enter to pick status:', '↑↓ to move', 'Esc to close']],
        ['sta', 2, ['Enter to search', 'Tab or → to pick status:', '↑↓ to move', 'Esc to close']],
        ['sta', 0, ['Enter or Tab to pick status:', '↑↓ to move', 'Esc to close']],
        ['status:', 0, ['Enter or Tab to add filter', '↑↓ to move', 'Esc to close']],
    ])('hint row for %j with row %s highlighted', (input, highlight, hints) => {
        mountWith({ filters: [], text: '' })
        logic.actions.setInput(input)
        logic.actions.moveHighlight(highlight)
        expect(logic.values.hints).toEqual(hints)
    })
})
