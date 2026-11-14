import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'

import { initKeaTests } from '~/test/init'

import { FacetDefinition, FacetSearchValue, serializeFacetQuery } from './facetQuery'
import { FacetSearchBar } from './FacetSearchBar'

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
        getValues: (item) => [item.status],
        formatValue: (value) => value[0].toUpperCase() + value.slice(1),
    },
    {
        key: 'sends',
        label: 'Sends',
        description: 'Email subject',
        freeTextValues: true,
        getValues: (item) => item.subjects,
    },
]

const ITEMS: Item[] = [
    { name: 'Welcome', status: 'active', subjects: ['Your trial ends'] },
    { name: 'Renewal', status: 'draft', subjects: [] },
    { name: 'Promo', status: 'archived', subjects: [] },
]

const matchesText = (item: Item, text: string): boolean => item.name.toLowerCase().includes(text.toLowerCase())

function Harness({
    initial,
    facets = FACETS,
}: {
    initial: FacetSearchValue
    facets?: FacetDefinition<Item>[]
}): JSX.Element {
    const [value, setValue] = useState(initial)
    return (
        <div>
            <FacetSearchBar
                facets={facets}
                items={ITEMS}
                value={value}
                onChange={setValue}
                matchesText={matchesText}
                placeholder="Search"
                dataAttr="test-search"
            />
            <button type="button" onClick={() => setValue({ filters: [], text: '' })}>
                Clear filters
            </button>
            <div data-attr="query">{serializeFacetQuery(value.filters)}</div>
            <div data-attr="text">{value.text}</div>
        </div>
    )
}

const input = (): HTMLInputElement => document.querySelector<HTMLInputElement>('input[data-attr="test-search"]')!
const shown = (attr: string): string => document.querySelector(`[data-attr="${attr}"]`)?.textContent ?? ''
const listbox = (): Element | null => document.querySelector('[role="listbox"]')

let user: ReturnType<typeof userEvent.setup>

async function clickInput(): Promise<void> {
    await user.click(input())
}

/** Types at the caret, as a user who has already clicked into the input does. */
async function typeText(text: string): Promise<void> {
    await user.type(input(), text, { skipClick: true })
}

async function press(key: string): Promise<void> {
    await user.keyboard(`{${key}}`)
}

async function paste(text: string): Promise<void> {
    await user.paste(text)
}

describe('FacetSearchBar', () => {
    beforeEach(() => {
        initKeaTests()
        user = userEvent.setup()
    })
    afterEach(() => cleanup())

    const setup = (initial: FacetSearchValue = { filters: [], text: '' }): void => {
        render(<Harness initial={initial} />)
    }

    it('Tab and → take the first filter row, never the search row', async () => {
        setup()
        await clickInput()
        await typeText('sta')
        await press('ArrowDown')
        expect(document.querySelector('[role="option"][aria-selected="true"]')).toHaveTextContent('Search for "sta"')

        await press('Tab')
        expect(input()).toHaveValue('status:')
        expect(shown('text')).toEqual('')

        await typeText('act')
        await press('ArrowRight')
        expect(shown('query')).toEqual('status:active')
        expect(input()).toHaveValue('')
        expect(input()).toHaveFocus()
    })

    it('Enter on the search row closes the popover and keeps the text', async () => {
        setup()
        await clickInput()
        await typeText('renew')
        expect(listbox()).not.toBeNull()

        await press('Enter')
        expect(listbox()).toBeNull()
        expect(input()).toHaveValue('renew')
        expect(shown('text')).toEqual('renew')
        expect(shown('query')).toEqual('')
    })

    it('Esc closes the popover, and a click on the focused input opens it again', async () => {
        setup()
        await clickInput()
        expect(listbox()).not.toBeNull()
        await press('Escape')
        expect(listbox()).toBeNull()
        await clickInput()
        expect(listbox()).not.toBeNull()
    })

    it('Backspace on an empty input removes the last pill', async () => {
        setup({
            filters: [
                { facet: 'status', value: 'draft', negated: false },
                { facet: 'status', value: 'archived', negated: true },
            ],
            text: '',
        })
        await clickInput()
        await press('Backspace')
        expect(shown('query')).toEqual('status:draft')
    })

    it('leaves Tab on an empty input to the browser', async () => {
        setup()
        await clickInput()
        await press('Tab')
        expect(input()).not.toHaveFocus()
        expect(input()).toHaveValue('')
    })

    it.each([
        ['a typed facet value followed by a space', 'status:active ', 'status:active', ''],
        ['a closed quoted value', 'sends:"Your trial ends"', 'sends:"Your trial ends"', ''],
        ['text around a typed facet value', 'wel status:active ren', 'status:active', 'wel ren'],
        [
            'a quoted value that holds a facet token',
            'sends:"Check status:active now" wel',
            'sends:"Check status:active now"',
            'wel',
        ],
    ])('turns %s into a pill', async (_, typed, query, text) => {
        setup()
        await clickInput()
        await typeText(typed)
        expect(shown('query')).toEqual(query)
        expect(shown('text')).toEqual(text)
    })

    it.each([
        ['a pasted query', 'status:draft -status:archived'],
        [
            'a pasted quoted value that ends in a backslash',
            serializeFacetQuery([
                { facet: 'sends', value: 'Path C:\\', negated: false },
                { facet: 'status', value: 'active', negated: false },
            ]),
        ],
    ])('turns %s into pills', async (_, query) => {
        setup()
        await clickInput()
        await paste(`${query} `)
        expect(shown('query')).toEqual(query)
        expect(input()).toHaveValue('')
    })

    it.each([
        ['pasted', paste],
        ['typed one character at a time', typeText],
    ])('reads a long query with quotes and escapes the same way when %s', async (_, enter) => {
        const filters = [
            ...Array.from({ length: 12 }, (_, index) => ({
                facet: 'sends',
                value: `Deal ${index} "x status:active \\`,
                negated: false,
            })),
            { facet: 'status', value: 'draft', negated: false },
        ]
        const openQuote = 'sends:"Open status:archived '
        setup()
        await clickInput()
        await enter(`${serializeFacetQuery(filters)} ${openQuote}`)
        expect(shown('query')).toEqual(serializeFacetQuery(filters))
        expect(input()).toHaveValue(openQuote)
    })

    it('adds a pasted token once, even when the paste repeats it', async () => {
        setup()
        await clickInput()
        await paste('status:active status:active ')
        expect(shown('query')).toEqual('status:active')
        expect(document.querySelectorAll('[aria-label="Remove filter Status: Active"]')).toHaveLength(1)
    })

    it('leaves Shift+Tab to the browser instead of applying a filter', async () => {
        setup()
        await clickInput()
        await typeText('sta')
        await user.keyboard('{Shift>}{Tab}{/Shift}')
        expect(input()).not.toHaveFocus()
        expect(shown('query')).toEqual('')
    })

    it.each([
        ['flags the composition', { isComposing: true }],
        ['sends key code 229, as Safari does', { keyCode: 229 }],
    ])('Enter while an IME %s does not apply the highlighted row', async (_, composition) => {
        setup()
        await clickInput()
        await typeText('status:')
        fireEvent.keyDown(input(), { key: 'Enter', ...composition })
        expect(shown('query')).toEqual('')
        expect(input()).toHaveValue('status:')
    })

    it.each([
        ['a value that names one option', 'status:active', 'status:active'],
        ['a value and a space', 'status:draft ', 'status:draft'],
        ['a closed quoted value', 'sends:"Your trial ends"', 'sends:"Your trial ends"'],
    ])('adds %s as a pill only once the IME composition ends', async (_, composed, query) => {
        setup()
        await clickInput()
        fireEvent.compositionStart(input())
        fireEvent.change(input(), { target: { value: composed } })
        expect(shown('query')).toEqual('')
        expect(input()).toHaveValue(composed)

        fireEvent.compositionEnd(input())
        expect(shown('query')).toEqual(query)
        expect(input()).toHaveValue('')
    })

    it('leaves a value composed in its middle as a draft when the composition ends', async () => {
        setup()
        await clickInput()
        fireEvent.compositionStart(input())
        fireEvent.change(input(), { target: { value: 'status:active' } })
        input().setSelectionRange('status:act'.length, 'status:act'.length)
        fireEvent.compositionEnd(input())
        expect(shown('query')).toEqual('')
        expect(input()).toHaveValue('status:active')
    })

    it('leaves a value corrected in its middle as a draft', async () => {
        setup()
        await clickInput()
        await typeText('status:actiive')
        await press('ArrowLeft')
        await press('ArrowLeft')
        await press('ArrowLeft')
        await press('Backspace')
        expect(input()).toHaveValue('status:active')
        expect(shown('query')).toEqual('')
    })

    it('keeps focus in the input and the popover open when the popover chrome is pressed', async () => {
        setup()
        await clickInput()
        await user.click(document.querySelector('[data-attr="facet-search-bar-hints"]')!)
        expect(input()).toHaveFocus()
        expect(listbox()).not.toBeNull()
    })

    it('announces the no-values message as a status, with no list of options', async () => {
        setup()
        await clickInput()
        await typeText('status:zzz')
        expect(screen.getByRole('status')).toHaveTextContent('No value matches "zzz"')
        expect(screen.queryByRole('listbox')).toBeNull()
        expect(screen.getByRole('combobox')).toHaveAttribute('aria-expanded', 'false')
        expect(screen.getByRole('combobox')).not.toHaveAttribute('aria-controls')
        expect(screen.getByRole('combobox')).not.toHaveAttribute('aria-activedescendant')
    })

    it('drops a half-typed filter when the parent clears the filters', async () => {
        setup({ filters: [{ facet: 'status', value: 'draft', negated: false }], text: '' })
        await clickInput()
        await typeText('status:arch')
        await user.click(screen.getByText('Clear filters'))
        expect(input()).toHaveValue('')

        await clickInput()
        await press('Enter')
        expect(shown('query')).toEqual('')
    })

    it('keeps focus in the input after a pill is removed with the keyboard', async () => {
        setup({ filters: [{ facet: 'status', value: 'draft', negated: false }], text: '' })
        const remove = document.querySelector<HTMLElement>('[aria-label="Remove filter Status: Draft"]')!
        remove.focus()
        await press('Enter')
        expect(shown('query')).toEqual('')
        expect(input()).toHaveFocus()
    })

    it('removes only the pill clicked, and keeps the other pill in place, when two differ only in case', async () => {
        const folder: FacetDefinition<Item> = {
            key: 'folder',
            label: 'Folder',
            description: 'Exact folder',
            caseSensitive: true,
            getValues: () => [],
        }
        render(
            <Harness
                facets={[...FACETS, folder]}
                initial={{
                    filters: [
                        { facet: 'folder', value: 'billing', negated: false },
                        { facet: 'folder', value: 'Billing', negated: false },
                    ],
                    text: '',
                }}
            />
        )
        const pills = (): Element[] => [...document.querySelectorAll('[data-attr="test-search-pill"]')]
        const kept = pills()[1]

        await user.click(document.querySelector('[aria-label="Remove filter Folder: billing"]')!)

        expect(shown('query')).toEqual('folder:Billing')
        expect(pills()).toEqual([kept])
        expect(kept.textContent).toEqual('Folder: Billing')
    })

    it('exposes the combobox, labels each pill remove button, and keeps the values out of autocapture', async () => {
        setup({ filters: [{ facet: 'status', value: 'draft', negated: true }], text: '' })
        expect(input()).toHaveAttribute('role', 'combobox')
        expect(input()).toHaveAttribute('aria-expanded', 'false')
        const remove = document.querySelector('[aria-label="Remove filter Status is not: Draft"]')
        expect(remove?.closest('.ph-no-capture')).not.toBeNull()
        expect(document.querySelector('[title="Status is not: Draft"]')?.closest('.ph-no-capture')).not.toBeNull()

        await clickInput()
        await typeText('status:')
        expect(input()).toHaveAttribute('aria-expanded', 'true')
        expect(input().getAttribute('aria-controls')).toEqual(listbox()!.id)
        const selected = document.querySelector('[role="option"][aria-selected="true"]')!
        expect(input().getAttribute('aria-activedescendant')).toEqual(selected.id)
        expect(shown('facet-search-bar-hints')).toContain('Esc to close')

        await user.clear(input())
        await typeText('sends:')
        expect(
            document.querySelector('[role="option"] [title="Your trial ends"]')?.closest('.ph-no-capture')
        ).not.toBeNull()
    })
})
