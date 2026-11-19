import { normalizeSpeed } from './feedModel'
import { HOLD_PULL, holdRateFor, playbackRate, pullHold, releaseHold, startHold } from './holdLock'

describe('speeds, hold and pull-down lock', () => {
    test.each([
        [0.5, 2],
        [1, 2],
        [1.5, 2],
        [2, 4],
        [4, null],
    ])('a hold at speed %s plays at %s', (speed, rate) => {
        expect(holdRateFor(speed)).toBe(rate)
        expect(startHold(speed, null)?.rate ?? null).toBe(rate)
    })

    test.each([
        [3, 2],
        [8, 4],
        [16, 4],
        [1.5, 1.5],
        ['fast', 1],
    ])('a stored speed of %s becomes %s', (stored, speed) => {
        expect(normalizeSpeed(stored)).toBe(speed)
    })

    test.each([
        ['locks when released past the pull', null, HOLD_PULL, false, { rate: 2 }, 'locked'],
        ['does nothing when released short of the pull', null, HOLD_PULL - 1, false, null, null],
        ['does nothing when the gesture is cancelled', null, HOLD_PULL + 40, true, null, null],
        ['unlocks a lock when released past the pull', { rate: 4 }, HOLD_PULL + 10, false, null, 'unlocked'],
        ['keeps the lock when released short of the pull', { rate: 4 }, 10, false, { rate: 4 }, null],
    ] as const)('%s', (_name, lock, pull, cancelled, nextLock, result) => {
        const hold = startHold(1, lock)
        if (!hold) {
            throw new Error('expected a hold')
        }
        expect(playbackRate(1, hold, lock)).toBe(lock?.rate ?? 2)
        expect(releaseHold(pullHold(hold, pull), lock, cancelled)).toEqual({ lock: nextLock, result })
    })

    test('a pull back above the threshold disarms the hold', () => {
        const hold = startHold(1, null) as NonNullable<ReturnType<typeof startHold>>
        const back = pullHold(pullHold(hold, HOLD_PULL + 20), 30)
        expect(releaseHold(back, null, false)).toEqual({ lock: null, result: null })
    })
})
