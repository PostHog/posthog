import { act, renderHook } from '@testing-library/react'

import { ADVENT_CARD_CLOSE_MS, useAdventCard } from './useAdventCard'

const FRAMES_MS = 40

describe('useAdventCard', () => {
    beforeEach(() => {
        jest.useFakeTimers()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it('opens the card of a hovered door at once, follows the pointer across doors, and closes once it leaves', () => {
        const { result } = renderHook(() => useAdventCard(null, true))
        const shown = (): { doorId: string | null; isOpen: boolean } => ({
            doorId: result.current.doorId,
            isOpen: result.current.isOpen,
        })

        act(() => result.current.onEnterDoor('door-1'))
        act(() => jest.advanceTimersByTime(FRAMES_MS))
        expect(shown()).toEqual({ doorId: 'door-1', isOpen: true })

        for (const doorId of ['door-2', 'door-3-upper', 'door-4-upper']) {
            act(() => result.current.onLeaveDoor())
            act(() => result.current.onEnterDoor(doorId))
            act(() => jest.advanceTimersByTime(FRAMES_MS))
            expect(shown()).toEqual({ doorId, isOpen: true })
        }

        act(() => result.current.onLeaveDoor())
        act(() => jest.advanceTimersByTime(ADVENT_CARD_CLOSE_MS))
        act(() => jest.advanceTimersByTime(ADVENT_CARD_CLOSE_MS))
        expect(shown()).toEqual({ doorId: null, isOpen: false })
    })
})
