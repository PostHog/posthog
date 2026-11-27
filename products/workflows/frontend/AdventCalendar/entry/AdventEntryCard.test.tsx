import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import posthog from 'posthog-js'

import { initKeaTests } from '~/test/init'

import { ADVENT_YEAR } from '../adventContent'
import { PROGRESS_STORAGE_KEY } from '../adventProgressStorage'
import { AdventEntryCard } from './AdventEntryCard'

function storeProgress(opened: number[], answers: Record<number, string>): void {
    window.localStorage.setItem(PROGRESS_STORAGE_KEY, JSON.stringify({ [MOCK_DEFAULT_USER.uuid]: { opened, answers } }))
}

describe('AdventEntryCard', () => {
    beforeEach(() => {
        jest.useFakeTimers({ now: new Date(ADVENT_YEAR, 11, 3, 9) })
        window.localStorage.clear()
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
        jest.useRealTimers()
        jest.restoreAllMocks()
    })

    it.each([
        ['nothing opened yet', [], {}, 'You opened 0 of 24 doors. Today is door 3.'],
        [
            'two doors opened before today',
            [1, 2],
            { 2: 'james' },
            'You opened 2 of 24 doors. Your hedgehogs: Remote Work, James Hawkins. Today is door 3.',
        ],
        [
            "today's door opened",
            [1, 2, 3],
            { 2: 'james' },
            'You opened 3 of 24 doors. Your hedgehogs: Remote Work, James Hawkins, Safari. Today is door 3.',
        ],
    ])('tells a screen reader the doors and hedgehogs with %s', (_, opened, answers, summary) => {
        storeProgress(opened, answers)

        render(<AdventEntryCard />)

        expect(screen.getByText(summary)).toBeTruthy()
    })

    it.each<[string, (button: HTMLElement) => void]>([
        ['a click', (button) => fireEvent.click(button)],
        ['a Cmd-click', (button) => fireEvent.click(button, { metaKey: true })],
        ['a Ctrl-click', (button) => fireEvent.click(button, { ctrlKey: true })],
        ['a middle click', (button) => fireEvent(button, new MouseEvent('auxclick', { bubbles: true, button: 1 }))],
    ])('reports %s on the button once', (_, open) => {
        const captured: [string, unknown][] = []
        jest.spyOn(posthog, 'capture').mockImplementation((event, properties) => {
            captured.push([event, properties])
            return undefined
        })
        render(<AdventEntryCard />)

        open(screen.getByText('Open door 1'))

        expect(captured.filter(([event]) => event.startsWith('workflows advent'))).toEqual([
            ['workflows advent entry clicked', { entry: 'card', nav: undefined, has_workflows: null }],
        ])
    })
})
