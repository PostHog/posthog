import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { TurnHoverStore } from '../utils/turnHoverStore'
import { TurnReveal } from './TurnReveal'

describe('TurnReveal', () => {
    let store: TurnHoverStore

    function wrapper(label: string): JSX.Element {
        return (
            <TurnReveal key={label} store={store} turnId="turn-1">
                <span>{label}</span>
            </TurnReveal>
        )
    }

    beforeEach(() => {
        jest.useFakeTimers()
        store = new TurnHoverStore()
    })

    afterEach(() => {
        cleanup()
        jest.useRealTimers()
    })

    // The virtualizer recycles rows out of the DOM, and removing a hovered node fires no mouseleave.
    test.each([
        ['the pointer is inside it', 'row', null],
        ['the pointer is on the trailer of the same turn', 'trailer', 'turn-1'],
    ])('unmounting a row clears the hovered turn when %s', (_name, hovered, expected) => {
        const { rerender } = render(
            <>
                {wrapper('row')}
                {wrapper('trailer')}
            </>
        )
        fireEvent.mouseEnter(screen.getByText(hovered).parentElement!)
        expect(store.getHoveredTurnId()).toBe('turn-1')

        rerender(<>{wrapper('trailer')}</>)
        jest.runOnlyPendingTimers()

        expect(store.getHoveredTurnId()).toBe(expected)
    })
})
