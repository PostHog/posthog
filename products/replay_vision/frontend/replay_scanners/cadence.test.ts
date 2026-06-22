import { CadenceState, cadenceToRrule, DEFAULT_CADENCE, humanizeCadence, parseRruleToCadence } from './cadence'

describe('cadence', () => {
    it('builds a daily rrule with the time of day in BYHOUR/BYMINUTE', () => {
        expect(cadenceToRrule({ frequency: 'daily', weekdays: [], hour: 9, minute: 0 })).toBe(
            'FREQ=DAILY;BYHOUR=9;BYMINUTE=0'
        )
    })

    it('builds a weekly rrule with sorted BYDAY', () => {
        expect(cadenceToRrule({ frequency: 'weekly', weekdays: [2, 0], hour: 14, minute: 30 })).toBe(
            'FREQ=WEEKLY;BYDAY=MO,WE;BYHOUR=14;BYMINUTE=30'
        )
    })

    it('omits BYDAY for weekly with no weekdays selected', () => {
        expect(cadenceToRrule({ frequency: 'weekly', weekdays: [], hour: 8, minute: 0 })).toBe(
            'FREQ=WEEKLY;BYHOUR=8;BYMINUTE=0'
        )
    })

    it('builds a monthly rrule and ignores weekdays', () => {
        expect(cadenceToRrule({ frequency: 'monthly', weekdays: [3], hour: 7, minute: 15 })).toBe(
            'FREQ=MONTHLY;BYHOUR=7;BYMINUTE=15'
        )
    })

    it.each<[string, CadenceState]>([
        ['daily', { frequency: 'daily', weekdays: [], hour: 9, minute: 0 }],
        ['weekly+weekdays', { frequency: 'weekly', weekdays: [0, 2, 4], hour: 14, minute: 30 }],
        ['monthly', { frequency: 'monthly', weekdays: [], hour: 23, minute: 59 }],
    ])('round-trips %s', (_label, state) => {
        expect(parseRruleToCadence(cadenceToRrule(state))).toEqual(state)
    })

    it('falls back to the default cadence on empty or unrecognized rrule', () => {
        expect(parseRruleToCadence(undefined)).toEqual(DEFAULT_CADENCE)
        expect(parseRruleToCadence('')).toEqual(DEFAULT_CADENCE)
        expect(parseRruleToCadence('FREQ=YEARLY;BYHOUR=9;BYMINUTE=0')).toEqual(DEFAULT_CADENCE)
    })

    it('clamps out-of-range time components back to the default', () => {
        const parsed = parseRruleToCadence('FREQ=DAILY;BYHOUR=99;BYMINUTE=0')
        expect(parsed.hour).toBe(DEFAULT_CADENCE.hour)
        expect(parsed.minute).toBe(0)
    })

    it('humanizes each frequency', () => {
        expect(humanizeCadence({ frequency: 'daily', weekdays: [], hour: 9, minute: 5 })).toBe('Daily at 09:05')
        expect(humanizeCadence({ frequency: 'weekly', weekdays: [0, 2], hour: 14, minute: 0 })).toBe(
            'Weekly on Mon, Wed at 14:00'
        )
        expect(humanizeCadence({ frequency: 'weekly', weekdays: [], hour: 8, minute: 0 })).toBe(
            'Weekly on every day at 08:00'
        )
        expect(humanizeCadence({ frequency: 'monthly', weekdays: [], hour: 7, minute: 30 })).toBe('Monthly at 07:30')
    })
})
