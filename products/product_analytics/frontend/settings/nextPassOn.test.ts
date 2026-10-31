import { EventsPassSchedule, nextPassOn } from './nextPassOn'

const SCHEDULED: EventsPassSchedule = {
    scheduled_pass_on: '2026-12-03',
    first_pass_on: '2027-02-03',
    default_window_deletes: true,
}

describe('nextPassOn', () => {
    it.each([
        ['keeps the scheduled pass for an unchanged window', SCHEDULED, true, false, '2026-12-03'],
        ['waits at least 3 months for a shorter window', SCHEDULED, true, true, '2027-02-03'],
        [
            'keeps a later scheduled pass for a shorter window',
            { ...SCHEDULED, scheduled_pass_on: '2027-05-03' },
            true,
            true,
            '2027-05-03',
        ],
        [
            'starts a newly set window at the first pass',
            { ...SCHEDULED, scheduled_pass_on: null },
            true,
            false,
            '2027-02-03',
        ],
        [
            'knows no date for a default window before admission',
            { ...SCHEDULED, scheduled_pass_on: null },
            false,
            false,
            null,
        ],
        [
            'deletes nothing past a default window the cleanup does not enforce',
            { ...SCHEDULED, default_window_deletes: false },
            false,
            true,
            null,
        ],
    ])('%s', (_name, schedule, isSet, isShorter, expected) => {
        expect(nextPassOn(schedule, { isSet, isShorter })).toEqual(expected)
    })
})
