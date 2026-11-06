import { autoResolveChangeEvent } from './autoResolveDays'

describe('autoResolveChangeEvent', () => {
    test.each([
        [null, 14, 'error tracking auto resolve enabled'],
        [14, null, 'error tracking auto resolve disabled'],
        [14, 30, 'error tracking auto resolve threshold changed'],
        [14, 14, null],
        [null, null, null],
    ])('from %p days to %p days sends %p', (previousDays, nextDays, expected) => {
        expect(autoResolveChangeEvent(previousDays, nextDays)).toEqual(expected)
    })
})
