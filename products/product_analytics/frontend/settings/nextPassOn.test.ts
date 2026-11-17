import { EventsPassSchedule, nextPassOn } from './nextPassOn'

const SCHEDULED: EventsPassSchedule = {
    scheduled_pass_on: '2026-12-03',
    first_pass_on: '2027-02-03',
    default_period_deletes: true,
}

describe('nextPassOn', () => {
    it.each([
        ['waits at least 3 months for a shorter period', SCHEDULED, '2027-02-03'],
        ['keeps a later scheduled pass', { ...SCHEDULED, scheduled_pass_on: '2027-05-03' }, '2027-05-03'],
        ['knows no date before admission', { ...SCHEDULED, scheduled_pass_on: null }, null],
        [
            'deletes nothing when the cleanup does not enforce the default',
            { ...SCHEDULED, default_period_deletes: false },
            null,
        ],
    ])('%s', (_name, schedule, expected) => {
        expect(nextPassOn(schedule)).toEqual(expected)
    })
})
