import { adventOpenedOnItsDay, adventTicketDays } from './adventTickets'

const BERLIN = 60
const LOS_ANGELES = -480

describe('advent tickets', () => {
    it.each([
        ['on its day', 3, '2026-12-03T09:00:00Z', 0, true],
        ['a day late', 3, '2026-12-04T09:00:00Z', 0, false],
        ['a day early', 3, '2026-12-02T09:00:00Z', 0, false],
        ['just after local midnight east of UTC', 4, '2026-12-03T23:30:00Z', BERLIN, true],
        ['just before local midnight west of UTC', 3, '2026-12-04T07:30:00Z', LOS_ANGELES, true],
        ['the UTC date when the local date differs', 4, '2026-12-04T07:30:00Z', LOS_ANGELES, false],
        ['door 24 on December 24', 24, '2026-12-24T18:00:00Z', BERLIN, true],
        ['door 24 after Christmas', 24, '2026-12-27T18:00:00Z', BERLIN, false],
        ['the same date a year early', 3, '2025-12-03T09:00:00Z', 0, false],
    ])('counts a door opened %s', (_, day, openedAt, offset, isOnTime) => {
        expect(adventOpenedOnItsDay(day, new Date(openedAt), offset)).toBe(isOnTime)
    })

    it('counts each opened door once and ignores on-time days that are not opened or out of range', () => {
        expect(adventTicketDays([1, 2, 3, 24], [3, 3, 1, 5, 0, 25, 24])).toEqual([3, 1, 24])
    })
})
