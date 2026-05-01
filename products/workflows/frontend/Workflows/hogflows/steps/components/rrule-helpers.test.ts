import { RRule } from 'rrule'

import { dayjs } from 'lib/dayjs'

import {
    buildSummary,
    computePreviewOccurrences,
    DEFAULT_STATE,
    fakeUtcToReal,
    frequencyToRRule,
    getNthWeekdayOfMonth,
    isOneTimeSchedule,
    ONE_TIME_RRULE,
    parseNaturalLanguage,
    parseRRuleToState,
    ScheduleState,
    scheduleToText,
    stateToRRule,
} from './rrule-helpers'

describe('rrule-helpers', () => {
    describe('frequencyToRRule', () => {
        test.each([
            ['daily', RRule.DAILY],
            ['weekly', RRule.WEEKLY],
            ['monthly', RRule.MONTHLY],
            ['yearly', RRule.YEARLY],
        ] as const)('%s maps to correct RRule constant', (freq, expected) => {
            expect(frequencyToRRule(freq)).toBe(expected)
        })
    })

    describe('isOneTimeSchedule', () => {
        test.each([
            [ONE_TIME_RRULE, true],
            ['FREQ=WEEKLY;COUNT=1', true],
            ['FREQ=DAILY;COUNT=2', false],
            ['FREQ=WEEKLY;INTERVAL=1', false],
            ['FREQ=MONTHLY;BYDAY=MO;BYSETPOS=1', false],
            ['invalid-rrule', false],
        ])('%s -> %s', (rrule, expected) => {
            expect(isOneTimeSchedule(rrule)).toBe(expected)
        })
    })

    describe('getNthWeekdayOfMonth', () => {
        test.each([
            ['2024-01-01', { n: 1, weekday: 0 }], // 1st Monday
            ['2024-01-08', { n: 2, weekday: 0 }], // 2nd Monday
            ['2024-01-17', { n: 3, weekday: 2 }], // 3rd Wednesday
            ['2024-01-24', { n: 4, weekday: 2 }], // 4th Wednesday
            ['2024-01-05', { n: 1, weekday: 4 }], // 1st Friday
            ['2024-01-20', { n: 3, weekday: 5 }], // 3rd Saturday
            ['2024-01-29', { n: 5, weekday: 0 }], // 5th Monday
        ])('date %s returns %o', (dateStr, expected) => {
            const result = getNthWeekdayOfMonth(dayjs(dateStr))
            expect(result).toEqual(expected)
        })
    })

    describe('parseRRuleToState', () => {
        it('parses daily with interval 2', () => {
            const result = parseRRuleToState('FREQ=DAILY;INTERVAL=2')
            expect(result.frequency).toBe('daily')
            expect(result.interval).toBe(2)
            expect(result.endType).toBe('never')
        })

        it('parses weekly with specific weekdays', () => {
            const result = parseRRuleToState('FREQ=WEEKLY;BYDAY=MO,WE,FR')
            expect(result.frequency).toBe('weekly')
            expect(result.interval).toBe(1)
            expect(result.weekdays).toEqual([0, 2, 4])
        })

        it('parses monthly day_of_month', () => {
            const result = parseRRuleToState('FREQ=MONTHLY;BYMONTHDAY=15')
            expect(result.frequency).toBe('monthly')
            expect(result.monthlyMode).toBe('day_of_month')
        })

        it('parses monthly nth_weekday with BYSETPOS', () => {
            const result = parseRRuleToState('FREQ=MONTHLY;BYDAY=WE;BYSETPOS=3')
            expect(result.frequency).toBe('monthly')
            expect(result.monthlyMode).toBe('nth_weekday')
        })

        it('parses monthly last_day (BYMONTHDAY=-1)', () => {
            const result = parseRRuleToState('FREQ=MONTHLY;BYMONTHDAY=-1')
            expect(result.frequency).toBe('monthly')
            expect(result.monthlyMode).toBe('last_day')
        })

        it('parses COUNT as after_count end type', () => {
            const result = parseRRuleToState('FREQ=DAILY;COUNT=5')
            expect(result.endType).toBe('after_count')
            expect(result.endCount).toBe(5)
        })

        it('parses UNTIL as on_date end type', () => {
            const result = parseRRuleToState('FREQ=DAILY;UNTIL=20240630T235959Z')
            expect(result.endType).toBe('on_date')
            expect(result.endDate).not.toBeNull()
            expect(dayjs(result.endDate!).year()).toBe(2024)
            expect(dayjs(result.endDate!).month()).toBe(5) // 0-indexed June
        })

        it('returns DEFAULT_STATE for malformed input', () => {
            const result = parseRRuleToState('NOT_A_VALID_RRULE!!!!')
            expect(result).toEqual(DEFAULT_STATE)
        })
    })

    describe('stateToRRule', () => {
        const roundtrip = (state: ScheduleState, startsAt: string | null = null): ScheduleState => {
            const rruleStr = stateToRRule(state, startsAt)
            return parseRRuleToState(rruleStr)
        }

        it('roundtrips daily every 3 days', () => {
            const state: ScheduleState = { ...DEFAULT_STATE, frequency: 'daily', interval: 3 }
            const parsed = roundtrip(state)
            expect(parsed.frequency).toBe('daily')
            expect(parsed.interval).toBe(3)
        })

        it('roundtrips weekly on Mon, Wed, Fri', () => {
            const state: ScheduleState = { ...DEFAULT_STATE, frequency: 'weekly', weekdays: [0, 2, 4] }
            const parsed = roundtrip(state)
            expect(parsed.frequency).toBe('weekly')
            expect(parsed.weekdays).toEqual([0, 2, 4])
        })

        it('roundtrips monthly on the 15th', () => {
            const state: ScheduleState = { ...DEFAULT_STATE, frequency: 'monthly', monthlyMode: 'day_of_month' }
            const parsed = roundtrip(state, '2024-01-15')
            expect(parsed.frequency).toBe('monthly')
            expect(parsed.monthlyMode).toBe('day_of_month')
        })

        it('roundtrips monthly last day', () => {
            const state: ScheduleState = { ...DEFAULT_STATE, frequency: 'monthly', monthlyMode: 'last_day' }
            const rruleStr = stateToRRule(state, '2024-01-31')
            expect(rruleStr).toContain('BYMONTHDAY=-1')
            const parsed = parseRRuleToState(rruleStr)
            expect(parsed.monthlyMode).toBe('last_day')
        })

        it('roundtrips with end count', () => {
            const state: ScheduleState = { ...DEFAULT_STATE, frequency: 'daily', endType: 'after_count', endCount: 7 }
            const parsed = roundtrip(state)
            expect(parsed.endType).toBe('after_count')
            expect(parsed.endCount).toBe(7)
        })

        it('roundtrips with end date', () => {
            const state: ScheduleState = {
                ...DEFAULT_STATE,
                frequency: 'daily',
                endType: 'on_date',
                endDate: '2024-12-31T00:00:00.000Z',
            }
            const parsed = roundtrip(state)
            expect(parsed.endType).toBe('on_date')
            expect(parsed.endDate).not.toBeNull()
            expect(dayjs(parsed.endDate!).year()).toBe(2024)
            expect(dayjs(parsed.endDate!).month()).toBe(11) // 0-indexed December
        })

        it('produces a string without leading RRULE: prefix', () => {
            const state: ScheduleState = { ...DEFAULT_STATE, frequency: 'daily', interval: 1 }
            const result = stateToRRule(state, null)
            expect(result.startsWith('RRULE:')).toBe(false)
            expect(result).toContain('FREQ=DAILY')
        })
    })

    describe('computePreviewOccurrences', () => {
        const startsAt = '2030-01-15T09:00:00'

        it('returns 6 occurrences by default for never-ending schedule', () => {
            const state: ScheduleState = { ...DEFAULT_STATE, frequency: 'daily', endType: 'never' }
            const result = computePreviewOccurrences(state, startsAt)
            expect(result).toHaveLength(6)
        })

        it('respects explicit count param', () => {
            const state: ScheduleState = { ...DEFAULT_STATE, frequency: 'daily', endType: 'never' }
            const result = computePreviewOccurrences(state, startsAt, undefined, 3)
            expect(result).toHaveLength(3)
        })

        it('returns empty array for invalid startsAt', () => {
            const state: ScheduleState = { ...DEFAULT_STATE, frequency: 'daily' }
            const result = computePreviewOccurrences(state, 'not-a-date')
            expect(result).toEqual([])
        })

        it('limits to endCount when end type is after_count', () => {
            const state: ScheduleState = {
                ...DEFAULT_STATE,
                frequency: 'daily',
                endType: 'after_count',
                endCount: 4,
            }
            const result = computePreviewOccurrences(state, startsAt)
            expect(result).toHaveLength(4)
        })

        it('returns dates in ascending order starting from startsAt', () => {
            const state: ScheduleState = { ...DEFAULT_STATE, frequency: 'daily', endType: 'never' }
            const result = computePreviewOccurrences(state, startsAt)
            for (let i = 1; i < result.length; i++) {
                expect(result[i].getTime()).toBeGreaterThan(result[i - 1].getTime())
            }
            expect(result[0].getUTCFullYear()).toBe(2030)
            expect(result[0].getUTCMonth()).toBe(0) // January
            expect(result[0].getUTCDate()).toBe(15)
        })

        it('returns only future occurrences when dtstart is in the past', () => {
            const pastStartsAt = '2025-01-01T09:00:00'
            const state: ScheduleState = { ...DEFAULT_STATE, frequency: 'weekly', endType: 'never' }
            const result = computePreviewOccurrences(state, pastStartsAt)
            expect(result.length).toBeGreaterThan(0)
            expect(result.length).toBeLessThanOrEqual(6)
            for (const d of result) {
                expect(d.getTime()).toBeGreaterThan(Date.now())
            }
        })

        it('returns all future occurrences for finite schedules with past dtstart', () => {
            const pastStartsAt = '2025-01-01T09:00:00'
            const state: ScheduleState = {
                ...DEFAULT_STATE,
                frequency: 'monthly',
                endType: 'after_count',
                endCount: 50,
            }
            const result = computePreviewOccurrences(state, pastStartsAt)
            // Should return more than 6 for finite schedules so OccurrencesList can show the collapse
            expect(result.length).toBeGreaterThan(6)
            for (const d of result) {
                expect(d.getTime()).toBeGreaterThan(Date.now())
            }
        })
    })

    describe('fakeUtcToReal', () => {
        const fakeDate = new Date(Date.UTC(2026, 3, 3, 19, 25, 0))

        it.each([
            {
                label: 'reinterprets UTC values as the given timezone',
                timezone: 'Europe/Riga',
                expectedUtcHour: 16,
                expectedUtcMinute: 25,
            },
            {
                label: 'returns UTC-based dayjs when no timezone is given',
                timezone: undefined,
                expectedUtcHour: 19,
                expectedUtcMinute: 25,
            },
        ])('$label', ({ timezone, expectedUtcHour, expectedUtcMinute }) => {
            const real = fakeUtcToReal(fakeDate, timezone)
            // Verify the result is in UTC when no timezone is given (not local browser time)
            if (!timezone) {
                expect(real.isUTC()).toBe(true)
            }
            expect(real.utc().hour()).toBe(expectedUtcHour)
            expect(real.utc().minute()).toBe(expectedUtcMinute)
        })

        it('correctly identifies past occurrences across timezone offset', () => {
            const real = fakeUtcToReal(fakeDate, 'Europe/Riga')
            const afterInUtc = dayjs('2026-04-03T17:00:00Z')
            expect(real.isBefore(afterInUtc)).toBe(true)
        })
    })

    describe('buildSummary', () => {
        it('returns "Runs every day" for daily interval 1', () => {
            const state: ScheduleState = { ...DEFAULT_STATE, frequency: 'daily', interval: 1 }
            const result = buildSummary(state, null)
            expect(result).toContain('Runs every day')
        })

        it('returns interval string for daily interval 2', () => {
            const state: ScheduleState = { ...DEFAULT_STATE, frequency: 'daily', interval: 2 }
            const result = buildSummary(state, null)
            expect(result).toContain('Runs every 2 days')
        })

        it('returns biweekly with day names for weekly on Mon and Fri', () => {
            const state: ScheduleState = {
                ...DEFAULT_STATE,
                frequency: 'weekly',
                interval: 2,
                weekdays: [0, 4],
            }
            const result = buildSummary(state, null)
            expect(result).toContain('Runs every 2 weeks')
            expect(result).toContain('Monday')
            expect(result).toContain('Friday')
        })

        it('returns "on the last day" for monthly last_day', () => {
            const state: ScheduleState = { ...DEFAULT_STATE, frequency: 'monthly', monthlyMode: 'last_day' }
            const result = buildSummary(state, null)
            expect(result).toContain('Runs every month on the last day')
        })

        it('returns nth weekday label for monthly nth_weekday', () => {
            const state: ScheduleState = { ...DEFAULT_STATE, frequency: 'monthly', monthlyMode: 'nth_weekday' }
            // 2024-01-17 is the 3rd Wednesday
            const result = buildSummary(state, '2024-01-17')
            expect(result).toContain('on the 3rd Wednesday')
        })

        it('includes count when end type is after_count', () => {
            const state: ScheduleState = {
                ...DEFAULT_STATE,
                frequency: 'daily',
                endType: 'after_count',
                endCount: 10,
            }
            const result = buildSummary(state, null)
            expect(result).toContain('10 times')
        })

        it('includes end date when end type is on_date', () => {
            const state: ScheduleState = {
                ...DEFAULT_STATE,
                frequency: 'daily',
                endType: 'on_date',
                endDate: '2024-12-25T00:00:00.000Z',
            }
            const result = buildSummary(state, null)
            expect(result).toContain('until December 25, 2024')
        })

        it('includes starting date when startsAt is provided', () => {
            const state: ScheduleState = { ...DEFAULT_STATE, frequency: 'daily' }
            const result = buildSummary(state, '2024-06-01')
            expect(result).toContain('starting June 1')
        })

        it('ends with a period', () => {
            const state: ScheduleState = { ...DEFAULT_STATE, frequency: 'daily' }
            const result = buildSummary(state, null)
            expect(result.endsWith('.')).toBe(true)
        })
    })

    describe('parseNaturalLanguage', () => {
        it.each([
            ['every day', 'daily', 1, []],
            ['every 3 days', 'daily', 3, []],
            ['every week on Monday', 'weekly', 1, [0]],
            ['every week on Monday and Wednesday', 'weekly', 1, [0, 2]],
            ['every 2 weeks on Friday', 'weekly', 2, [4]],
            ['every month on the 1st', 'monthly', 1, []],
            ['every month on the last', 'monthly', 1, []],
            ['every year', 'yearly', 1, []],
        ])('parses "%s"', (text, expectedFreq, expectedInterval, expectedWeekdays) => {
            const result = parseNaturalLanguage(text)
            expect(result).not.toBeNull()
            expect(result!.frequency).toBe(expectedFreq)
            expect(result!.interval).toBe(expectedInterval)
            if (expectedWeekdays.length > 0) {
                expect(result!.weekdays).toEqual(expectedWeekdays)
            }
        })

        it('parses end count', () => {
            const result = parseNaturalLanguage('every day for 10 times')
            expect(result).not.toBeNull()
            expect(result!.endType).toBe('after_count')
            expect(result!.endCount).toBe(10)
        })

        it('returns null for invalid input', () => {
            expect(parseNaturalLanguage('not a schedule')).toBeNull()
            expect(parseNaturalLanguage('')).toBeNull()
            expect(parseNaturalLanguage('biweekly')).toBeNull()
        })
    })

    describe('scheduleToText', () => {
        it.each([
            ['every day', { ...DEFAULT_STATE, frequency: 'daily' as const }, 'every day'],
            [
                'every week on Monday, Wednesday',
                { ...DEFAULT_STATE, frequency: 'weekly' as const, weekdays: [0, 2] },
                'every week on Monday, Wednesday',
            ],
            [
                'every day for 10 times',
                { ...DEFAULT_STATE, frequency: 'daily' as const, endType: 'after_count' as const, endCount: 10 },
                'every day for 10 times',
            ],
        ])('converts state to "%s"', (_label, state, expected) => {
            expect(scheduleToText(state, null)).toBe(expected)
        })
    })
})
