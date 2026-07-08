import { CadenceState, cadenceToRrule, DEFAULT_CADENCE, humanizeCadence, parseRruleToCadence } from './cadence'

describe('cadence', () => {
    it('builds a daily rrule (all seven weekdays) with the time of day in BYHOUR/BYMINUTE', () => {
        expect(cadenceToRrule({ weekdays: [0, 1, 2, 3, 4, 5, 6], hour: 9, minute: 0 })).toBe(
            'FREQ=DAILY;BYHOUR=9;BYMINUTE=0'
        )
    })

    it('builds a weekly rrule with sorted BYDAY', () => {
        expect(cadenceToRrule({ weekdays: [2, 0], hour: 14, minute: 30 })).toBe(
            'FREQ=WEEKLY;BYDAY=MO,WE;BYHOUR=14;BYMINUTE=30'
        )
    })

    it('omits BYDAY when no weekdays are selected', () => {
        expect(cadenceToRrule({ weekdays: [], hour: 8, minute: 0 })).toBe('FREQ=WEEKLY;BYHOUR=8;BYMINUTE=0')
    })

    it.each<[string, CadenceState]>([
        ['daily (all seven)', { weekdays: [0, 1, 2, 3, 4, 5, 6], hour: 9, minute: 0 }],
        ['weekly subset', { weekdays: [0, 2, 4], hour: 14, minute: 30 }],
        ['single day', { weekdays: [6], hour: 23, minute: 59 }],
    ])('round-trips %s', (_label, state) => {
        expect(parseRruleToCadence(cadenceToRrule(state))).toEqual(state)
    })

    it('parses FREQ=DAILY back to all seven weekdays', () => {
        expect(parseRruleToCadence('FREQ=DAILY;BYHOUR=9;BYMINUTE=0')).toEqual({
            weekdays: [0, 1, 2, 3, 4, 5, 6],
            hour: 9,
            minute: 0,
        })
    })

    it('normalizes legacy weekly-without-BYDAY to all seven weekdays', () => {
        expect(parseRruleToCadence('FREQ=WEEKLY;BYHOUR=8;BYMINUTE=0')).toEqual({
            weekdays: [0, 1, 2, 3, 4, 5, 6],
            hour: 8,
            minute: 0,
        })
    })

    it('falls back to the default cadence on empty, monthly, or unrecognized rrule', () => {
        expect(parseRruleToCadence(undefined)).toEqual(DEFAULT_CADENCE)
        expect(parseRruleToCadence('')).toEqual(DEFAULT_CADENCE)
        expect(parseRruleToCadence('FREQ=MONTHLY;BYHOUR=7;BYMINUTE=15')).toEqual(DEFAULT_CADENCE)
        expect(parseRruleToCadence('FREQ=YEARLY;BYHOUR=9;BYMINUTE=0')).toEqual(DEFAULT_CADENCE)
    })

    it('clamps out-of-range time components back to the default', () => {
        const parsed = parseRruleToCadence('FREQ=DAILY;BYHOUR=99;BYMINUTE=0')
        expect(parsed.hour).toBe(DEFAULT_CADENCE.hour)
        expect(parsed.minute).toBe(0)
    })

    it('humanizes the cadence from the selected weekdays', () => {
        expect(humanizeCadence({ weekdays: [0, 1, 2, 3, 4, 5, 6], hour: 9, minute: 5 })).toBe('Daily at 09:05')
        expect(humanizeCadence({ weekdays: [0, 2], hour: 14, minute: 0 })).toBe('Weekly on Mon, Wed at 14:00')
        expect(humanizeCadence({ weekdays: [], hour: 8, minute: 0 })).toBe('Pick at least one day')
    })
})
