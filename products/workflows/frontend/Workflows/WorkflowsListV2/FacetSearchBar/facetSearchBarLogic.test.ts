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
        formatValue: (value) => value[0].toUpperCase() + value.slice(1),
    },
    {
        key: 'sends',
        aliases: ['subject'],
        label: 'Sends',
        description: 'Email subject',
        showOnFocus: true,
        order: 2,
        getValues: (item) => item.subjects,
    },
    { key: 'stage', label: 'Stage', description: 'Found by typing', order: 3, getValues: () => ['one'] },
]

const ITEMS: Item[] = [
    { name: 'Welcome', status: 'active', subjects: ['Start here', 'Status update'] },
    { name: 'Renewal', status: 'draft', subjects: ['Renew now'] },
    { name: 'Sync', status: 'draft', subjects: [] },
    { name: 'Promo', status: 'archived', subjects: ['Deals'] },
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
            ['facet', 'stage:', undefined],
            ['search', 'Search for "sta"', undefined],
            ['value', 'Sends: Start here', 1],
            ['value', 'Sends: Status update', 1],
        ])
        expect(logic.values.title).toEqual('Search or filter')
        expect(onChange).toHaveBeenLastCalledWith({ filters: [], text: 'sta' })
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

    it('says when no values are left', () => {
        mountWith({ filters: [], text: 'promo' })
        logic.actions.setInput('promo sends:renew')
        expect(logic.values.suggestions.map((s) => [s.kind, s.label])).toEqual([
            ['none', 'No values match your other filters'],
        ])
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

    it('matches the text once per item for a suggestion build, not once per facet', () => {
        const countingMatch = jest.fn(matchesText)
        logic = facetSearchBarLogic({
            id: 'test',
            facets: FACETS,
            items: ITEMS,
            value: { filters: [], text: 'e' },
            onChange,
            matchesText: countingMatch,
        })
        logic.mount()
        logic.actions.setInput('e st')
        countingMatch.mockClear()
        expect(logic.values.suggestions.length).toBeGreaterThan(0)
        expect(countingMatch.mock.calls.length).toBeLessThanOrEqual(ITEMS.length)
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
