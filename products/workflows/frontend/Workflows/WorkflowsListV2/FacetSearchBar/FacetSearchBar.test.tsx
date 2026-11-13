import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render } from '@testing-library/react'
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
    { key: 'sends', label: 'Sends', description: 'Email subject', getValues: (item) => item.subjects },
]

const ITEMS: Item[] = [
    { name: 'Welcome', status: 'active', subjects: ['Your trial ends'] },
    { name: 'Renewal', status: 'draft', subjects: [] },
    { name: 'Promo', status: 'archived', subjects: [] },
]

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
                matchesText={(item, text) => item.name.toLowerCase().includes(text.toLowerCase())}
                placeholder="Search"
                dataAttr="test-search"
            />
            <output data-attr="query">{serializeFacetQuery(value.filters)}</output>
            <output data-attr="text">{value.text}</output>
        </div>
    )
}

const input = (): HTMLInputElement => document.querySelector<HTMLInputElement>('input[data-attr="test-search"]')!
const shown = (attr: string): string => document.querySelector(`[data-attr="${attr}"]`)?.textContent ?? ''
const listbox = (): Element | null => document.querySelector('[role="listbox"]')

const setInputValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!

function changeInput(text: string, caret: number = text.length): void {
    const field = input()
    setInputValue.call(field, text)
    field.setSelectionRange(caret, caret)
    fireEvent.input(field)
}

function clickInput(): void {
    input().focus()
    fireEvent.click(input())
}

function typeText(text: string): void {
    for (const character of text) {
        const field = input()
        if (fireEvent.keyDown(field, { key: character })) {
            const start = field.selectionStart ?? field.value.length
            const end = field.selectionEnd ?? start
            changeInput(field.value.slice(0, start) + character + field.value.slice(end), start + 1)
        }
    }
}

function press(key: string, init: KeyboardEventInit = {}): boolean {
    const field = input()
    const notPrevented = fireEvent.keyDown(field, { key, ...init })
    const caret = field.selectionStart ?? field.value.length
    if (notPrevented && key === 'ArrowLeft') {
        field.setSelectionRange(Math.max(0, caret - 1), Math.max(0, caret - 1))
    }
    if (notPrevented && key === 'Backspace' && caret > 0) {
        changeInput(field.value.slice(0, caret - 1) + field.value.slice(caret), caret - 1)
    }
    return notPrevented
}

/** Presses an element as a browser does: an unprevented mousedown moves the focus before the click. */
function pressPointer(element: Element): void {
    if (fireEvent.mouseDown(element)) {
        const focusable = element.closest<HTMLElement>('a[href], button, input, select, textarea, [tabindex]')
        act(() => (focusable ? focusable.focus() : (document.activeElement as HTMLElement | null)?.blur()))
    }
    fireEvent.mouseUp(element)
    fireEvent.click(element)
}

describe('FacetSearchBar', () => {
    beforeEach(() => initKeaTests())
    afterEach(() => cleanup())

    const setup = (initial: FacetSearchValue = { filters: [], text: '' }): void => {
        render(<Harness initial={initial} />)
    }

    it('Tab and → take the first filter row, never the search row', () => {
        setup()
        clickInput()
        typeText('sta')
        press('ArrowDown')
        expect(document.querySelector('[role="option"][aria-selected="true"]')).toHaveTextContent('Search for "sta"')

        press('Tab')
        expect(input()).toHaveValue('status:')
        expect(shown('text')).toEqual('')

        typeText('act')
        press('ArrowRight')
        expect(shown('query')).toEqual('status:active')
        expect(input()).toHaveValue('')
        expect(input()).toHaveFocus()
    })

    it('Enter on the search row closes the popover and keeps the text', () => {
        setup()
        clickInput()
        typeText('renew')
        expect(listbox()).not.toBeNull()

        press('Enter')
        expect(listbox()).toBeNull()
        expect(input()).toHaveValue('renew')
        expect(shown('text')).toEqual('renew')
        expect(shown('query')).toEqual('')
    })

    it('Esc closes the popover, and a click on the focused input opens it again', () => {
        setup()
        clickInput()
        expect(listbox()).not.toBeNull()
        press('Escape')
        expect(listbox()).toBeNull()
        clickInput()
        expect(listbox()).not.toBeNull()
    })

    it('Backspace on an empty input removes the last pill', () => {
        setup({
            filters: [
                { facet: 'status', value: 'draft', negated: false },
                { facet: 'status', value: 'archived', negated: true },
            ],
            text: '',
        })
        clickInput()
        press('Backspace')
        expect(shown('query')).toEqual('status:draft')
    })

    it('leaves Tab on an empty input to the browser', () => {
        setup()
        clickInput()
        expect(press('Tab')).toBe(true)
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
    ])('turns %s into a pill', (_, typed, query, text) => {
        setup()
        clickInput()
        typeText(typed)
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
    ])('turns %s into pills', (_, query) => {
        setup()
        clickInput()
        changeInput(`${query} `)
        expect(shown('query')).toEqual(query)
        expect(input()).toHaveValue('')
    })

    it.each([
        ['pasted', (text: string) => changeInput(text)],
        ['typed one character at a time', typeText],
    ])('reads a long query with quotes and escapes the same way when %s', (_, enter) => {
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
        clickInput()
        enter(`${serializeFacetQuery(filters)} ${openQuote}`)
        expect(shown('query')).toEqual(serializeFacetQuery(filters))
        expect(input()).toHaveValue(openQuote)
    })

    it('adds a pasted token once, even when the paste repeats it', () => {
        setup()
        clickInput()
        changeInput('status:active status:active ')
        expect(shown('query')).toEqual('status:active')
        expect(document.querySelectorAll('[aria-label="Remove filter Status: Active"]')).toHaveLength(1)
    })

    it('leaves Shift+Tab to the browser instead of applying a filter', () => {
        setup()
        clickInput()
        typeText('sta')
        // A Tab the bar does not prevent leaves the browser to move the focus.
        expect(press('Tab', { shiftKey: true })).toBe(true)
        expect(shown('query')).toEqual('')
    })

    it.each([
        ['flags the composition', { isComposing: true }],
        ['sends key code 229, as Safari does', { keyCode: 229 }],
    ])('Enter while an IME %s does not apply the highlighted row', (_, composition) => {
        setup()
        clickInput()
        typeText('status:')
        fireEvent.keyDown(input(), { key: 'Enter', ...composition })
        expect(shown('query')).toEqual('')
        expect(input()).toHaveValue('status:')
    })

    it.each([
        ['a value that names one option', 'status:active', 'status:active'],
        ['a value and a space', 'status:draft ', 'status:draft'],
        ['a closed quoted value', 'sends:"Your trial ends"', 'sends:"Your trial ends"'],
    ])('adds %s as a pill only once the IME composition ends', (_, composed, query) => {
        setup()
        clickInput()
        fireEvent.compositionStart(input())
        fireEvent.change(input(), { target: { value: composed } })
        expect(shown('query')).toEqual('')
        expect(input()).toHaveValue(composed)

        fireEvent.compositionEnd(input())
        expect(shown('query')).toEqual(query)
        expect(input()).toHaveValue('')
    })

    it('leaves a value composed in its middle as a draft when the composition ends', () => {
        setup()
        clickInput()
        fireEvent.compositionStart(input())
        fireEvent.change(input(), { target: { value: 'status:active' } })
        input().setSelectionRange('status:act'.length, 'status:act'.length)
        fireEvent.compositionEnd(input())
        expect(shown('query')).toEqual('')
        expect(input()).toHaveValue('status:active')
    })

    it('leaves a value corrected in its middle as a draft', () => {
        setup()
        clickInput()
        typeText('status:actiive')
        press('ArrowLeft')
        press('ArrowLeft')
        press('ArrowLeft')
        press('Backspace')
        expect(input()).toHaveValue('status:active')
        expect(shown('query')).toEqual('')
    })

    it('keeps focus in the input and the popover open when the popover chrome is pressed', () => {
        setup()
        clickInput()
        pressPointer(document.querySelector('[data-attr="facet-search-bar-hints"]')!)
        expect(input()).toHaveFocus()
        expect(listbox()).not.toBeNull()
    })

    it('scrolls the first row into view when typing changes the list', () => {
        // jsdom has no layout, so this records what the browser would be asked to scroll to.
        const scrolled: Element[] = []
        const scrollIntoView = Element.prototype.scrollIntoView
        Element.prototype.scrollIntoView = function (this: Element) {
            scrolled.push(this)
        }
        try {
            setup()
            clickInput()
            typeText('status:')
            scrolled.length = 0
            typeText('r')
            expect(scrolled).toHaveLength(1)
            expect(scrolled[0]).toHaveTextContent('Archived')
            expect(scrolled[0]).toHaveAttribute('aria-selected', 'true')
        } finally {
            Element.prototype.scrollIntoView = scrollIntoView
        }
    })

    it('shows the no-values message as text, not as an option', () => {
        setup()
        clickInput()
        typeText('status:zzz')
        expect(document.querySelectorAll('[role="option"]')).toHaveLength(0)
        expect(listbox()).toHaveTextContent('No value matches "zzz"')
        expect(input()).not.toHaveAttribute('aria-activedescendant')
    })

    it('keeps focus in the input after a pill is removed with the keyboard', () => {
        setup({ filters: [{ facet: 'status', value: 'draft', negated: false }], text: '' })
        const remove = document.querySelector<HTMLElement>('[aria-label="Remove filter Status: Draft"]')!
        remove.focus()
        fireEvent.click(remove)
        expect(shown('query')).toEqual('')
        expect(input()).toHaveFocus()
    })

    it('removes only the pill clicked, and keeps the other pill in place, when two differ only in case', () => {
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

        fireEvent.click(document.querySelector('[aria-label="Remove filter Folder: billing"]')!)

        expect(shown('query')).toEqual('folder:Billing')
        expect(pills()).toEqual([kept])
        expect(kept.textContent).toEqual('Folder: Billing')
    })

    it('exposes the combobox, labels each pill remove button, and keeps the values out of autocapture', () => {
        setup({ filters: [{ facet: 'status', value: 'draft', negated: true }], text: '' })
        expect(input()).toHaveAttribute('role', 'combobox')
        expect(input()).toHaveAttribute('aria-expanded', 'false')
        const remove = document.querySelector('[aria-label="Remove filter Status is not: Draft"]')
        expect(remove?.closest('.ph-no-capture')).not.toBeNull()
        expect(document.querySelector('[title="Status is not: Draft"]')?.closest('.ph-no-capture')).not.toBeNull()

        clickInput()
        typeText('status:')
        expect(input()).toHaveAttribute('aria-expanded', 'true')
        expect(input().getAttribute('aria-controls')).toEqual(listbox()!.id)
        const selected = document.querySelector('[role="option"][aria-selected="true"]')!
        expect(input().getAttribute('aria-activedescendant')).toEqual(selected.id)
        expect(shown('facet-search-bar-hints')).toContain('Esc to close')

        changeInput('')
        typeText('sends:')
        expect(
            document.querySelector('[role="option"] [title="Your trial ends"]')?.closest('.ph-no-capture')
        ).not.toBeNull()
    })
})
