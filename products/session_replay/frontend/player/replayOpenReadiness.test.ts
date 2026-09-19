import { CustomerJourney } from 'lib/customerJourneys/createCustomerJourney'

import { observeReplayOpenReadiness } from './replayOpenReadiness'

function setup(): {
    observer: ReturnType<typeof observeReplayOpenReadiness>
    journey: CustomerJourney
    firstPlayer: object
    state: { player: object | null; canPresent: boolean }
    frame: () => void
    callbacks: Map<number, FrameRequestCallback>
} {
    const journey: CustomerJourney = {
        attemptId: 'synthetic-replay-attempt',
        firstUseful: jest.fn(),
        finish: jest.fn(),
        dispose: jest.fn(),
    }
    const firstPlayer = {}
    const state = { player: firstPlayer as object | null, canPresent: true }
    const callbacks = new Map<number, FrameRequestCallback>()
    let nextId = 0
    const observer = observeReplayOpenReadiness(journey, () => state, {
        requestFrame: (callback) => {
            callbacks.set(++nextId, callback)
            return nextId
        },
        cancelFrame: (id) => callbacks.delete(id),
    })
    const frame = (): void => {
        const pending = [...callbacks.values()]
        callbacks.clear()
        pending.forEach((callback) => callback(0))
    }
    return { observer, journey, firstPlayer, state, frame, callbacks }
}

describe('replay open readiness', () => {
    it.each(['rebuild first', 'position first'] as const)(
        'waits for reconstruction, successful positioning and a presentation opportunity (%s)',
        (order) => {
            const { observer, journey, firstPlayer, frame } = setup()
            if (order === 'rebuild first') {
                observer.rebuilt(firstPlayer)
            } else {
                observer.positioned(firstPlayer)
            }
            frame()
            frame()
            expect(journey.finish).not.toHaveBeenCalled()
            if (order === 'rebuild first') {
                observer.positioned(firstPlayer)
            } else {
                observer.rebuilt(firstPlayer)
            }
            frame()
            expect(journey.finish).not.toHaveBeenCalled()
            frame()
            expect(journey.firstUseful).toHaveBeenCalledTimes(1)
            expect(journey.finish).toHaveBeenCalledWith('usable')
            observer.positioned(firstPlayer)
            observer.rebuilt(firstPlayer)
            frame()
            frame()
            expect(journey.finish).toHaveBeenCalledTimes(1)
        }
    )

    it.each([1, 2])('rechecks a paused frame after presentation was blocked at frame %s', (blockedFrame) => {
        const { observer, journey, firstPlayer, state, frame, callbacks } = setup()
        observer.rebuilt(firstPlayer)
        observer.positioned(firstPlayer)
        if (blockedFrame === 2) {
            frame()
        }
        state.canPresent = false
        frame()
        expect(journey.finish).not.toHaveBeenCalled()
        expect(callbacks.size).toBe(0)
        state.canPresent = true
        observer.presentationChanged()
        frame()
        expect(journey.finish).not.toHaveBeenCalled()
        frame()
        expect(journey.finish).toHaveBeenCalledTimes(1)
        observer.presentationChanged()
        expect(callbacks.size).toBe(0)
    })

    it('rejects a replaced player and waits for its own reconstruction after recovery or hide', () => {
        const { observer, journey, firstPlayer, state, frame } = setup()
        observer.rebuilt(firstPlayer)
        observer.positioned(firstPlayer)
        frame()
        state.player = null
        observer.reset()
        frame()
        expect(journey.finish).not.toHaveBeenCalled()
        const replacement = {}
        state.player = replacement
        observer.positioned(replacement)
        observer.rebuilt(firstPlayer)
        frame()
        frame()
        expect(journey.finish).not.toHaveBeenCalled()
        observer.rebuilt(replacement)
        frame()
        frame()
        expect(journey.finish).toHaveBeenCalledTimes(1)
    })

    it.each(['blocked', 'unmounted'] as const)('does not report usable when %s before the frame', (reason) => {
        const { observer, journey, firstPlayer, state, frame, callbacks } = setup()
        observer.rebuilt(firstPlayer)
        observer.positioned(firstPlayer)
        frame()
        if (reason === 'unmounted') {
            observer.dispose()
        } else {
            state.canPresent = false
        }
        expect(callbacks.size).toBe(reason === 'unmounted' ? 0 : 1)
        frame()
        expect(journey.finish).not.toHaveBeenCalled()
    })
})
