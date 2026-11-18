import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'

import { ShipIt } from './ShipIt'

/**
 * The rules are covered by shipItGame.test.ts. These cover the wiring the rules
 * cannot see: that the animation frame loop feeds them the clock, that the keys
 * reach them, and that the loop stops when the run is over.
 */
describe('ShipIt', () => {
    /** Each spawn draws three times: hazard or not, which item, which lane. */
    function seedSpawns(draws: number[]): void {
        let index = 0
        jest.spyOn(Math, 'random').mockImplementation(() => draws[index++ % draws.length])
    }

    /** Fake timers drive requestAnimationFrame, so the loop runs on the test's clock. */
    function advance(ms: number): void {
        act(() => {
            jest.advanceTimersByTime(ms)
        })
    }

    function laneOf(container: HTMLElement): string | null {
        return container.querySelector<HTMLElement>('.ShipIt__pr')?.style.top ?? null
    }

    beforeEach(() => {
        jest.useFakeTimers()
    })

    afterEach(() => {
        jest.useRealTimers()
        jest.restoreAllMocks()
        cleanup()
    })

    it('does not run the track until the player starts', () => {
        seedSpawns([0.9, 0.9, 0.5])
        const { container } = render(<ShipIt />)

        advance(5000)

        expect(container.querySelectorAll('.ShipIt__item')).toHaveLength(0)
        expect(screen.getByText('Open a pull request')).toBeTruthy()
    })

    it('runs the track once the player starts', () => {
        seedSpawns([0.9, 0.9, 0.5])
        const { container } = render(<ShipIt />)

        fireEvent.click(screen.getByText('Open a pull request'))
        advance(2000)

        expect(container.querySelectorAll('.ShipIt__item').length).toBeGreaterThan(0)
    })

    it('steers the pull request with the arrow keys', () => {
        seedSpawns([0.9, 0.9, 0.5])
        const { container } = render(<ShipIt />)
        fireEvent.click(screen.getByText('Open a pull request'))
        const board = container.querySelector('.ShipIt__board') as HTMLElement

        const middle = laneOf(container)
        fireEvent.keyDown(board, { key: 'ArrowDown' })
        const lower = laneOf(container)
        fireEvent.keyDown(board, { key: 'ArrowUp' })

        expect(lower).not.toEqual(middle)
        expect(laneOf(container)).toEqual(middle)
    })

    it('holds the pull request in the track at the top lane', () => {
        seedSpawns([0.9, 0.9, 0.5])
        const { container } = render(<ShipIt />)
        fireEvent.click(screen.getByText('Open a pull request'))
        const board = container.querySelector('.ShipIt__board') as HTMLElement
        const middle = laneOf(container)

        fireEvent.keyDown(board, { key: 'ArrowUp' })
        const top = laneOf(container)
        for (let press = 0; press < 4; press++) {
            fireEvent.keyDown(board, { key: 'ArrowUp' })
        }

        expect(top).not.toEqual(middle)
        expect(laneOf(container)).toEqual(top)
    })

    it('closes the pull request after three stale bots', () => {
        // A hazard, the third hazard kind, and the middle lane: a stale bot where the player starts.
        seedSpawns([0.1, 0.9, 0.4])
        render(<ShipIt />)
        fireEvent.click(screen.getByText('Open a pull request'))

        advance(12000)

        expect(screen.getByText('Closed as stale', { selector: 'h2' })).toBeTruthy()
    })

    it('stops the track when the scene unmounts', () => {
        seedSpawns([0.9, 0.9, 0.5])
        // The loop is only observable here: React drops the state updater once unmounted,
        // so a leaked loop still schedules frames while doing no visible work.
        const frames = jest.spyOn(window, 'requestAnimationFrame')
        const { unmount } = render(<ShipIt />)
        fireEvent.click(screen.getByText('Open a pull request'))
        advance(1000)

        unmount()
        const scheduled = frames.mock.calls.length
        advance(5000)

        expect(frames.mock.calls.length).toEqual(scheduled)
    })
})
