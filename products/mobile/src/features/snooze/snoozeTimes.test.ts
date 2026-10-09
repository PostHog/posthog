import { formatSnoozeWhen, parseCustomSnooze, snoozeLabels, snoozeUntil, type TimePreset } from './snoozeTimes'

// Local-time constructor arguments so the cases hold in any time zone.
const local = (y: number, m: number, d: number, h = 0, min = 0): Date => new Date(y, m - 1, d, h, min)

describe('snooze times', () => {
    test.each<[TimePreset, Date, Date, string]>([
        ['hour', local(2026, 10, 9, 14, 31), local(2026, 10, 9, 15, 31), '3:31 PM'],
        ['hour', local(2026, 10, 9, 23, 30), local(2026, 10, 10, 0, 30), '12:30 AM'],
        ['hour', local(2026, 10, 9, 11, 5), local(2026, 10, 9, 12, 5), '12:05 PM'],
        ['tomorrow', local(2026, 10, 9, 14, 31), local(2026, 10, 10, 9), 'Oct 10 at 9:00 AM'],
        ['tomorrow', local(2026, 10, 31, 22, 0), local(2026, 11, 1, 9), 'Nov 1 at 9:00 AM'],
        ['next_week', local(2026, 12, 28, 8, 0), local(2027, 1, 4, 9), 'Jan 4 at 9:00 AM'],
        ['month', local(2026, 10, 9, 14, 31), local(2026, 11, 8, 9), 'Nov 8 at 9:00 AM'],
    ])('%s from %s', (preset, now, expectedUntil, expectedLabel) => {
        const until = snoozeUntil(preset, now)
        expect(until.getTime()).toBe(expectedUntil.getTime())
        expect(formatSnoozeWhen(preset, until)).toBe(expectedLabel)
    })

    test.each([
        ['later today', local(2026, 10, 9, 15, 31), { row: 'Snoozed until 3:31 PM', activity: '3:31 PM' }],
        ['tomorrow', local(2026, 10, 10, 9), { row: 'Snoozed until tomorrow', activity: 'tomorrow, 9:00 AM' }],
        ['next week', local(2026, 10, 16, 9), { row: 'Snoozed until Oct 16', activity: 'Oct 16, 9:00 AM' }],
    ])('labels a snooze until %s', (_name, until, expected) => {
        const now = local(2026, 10, 9, 14, 31)
        expect(snoozeLabels({ kind: 'until', preset: 'custom', until: until.toISOString() }, now)).toEqual(expected)
    })

    test('labels a signal-count snooze', () => {
        expect(snoozeLabels({ kind: 'signals', count: 5 }, local(2026, 10, 9))).toEqual({
            row: 'Snoozed until more signals',
            activity: '5 more signals arrive',
        })
    })

    test.each<[string, Date | null]>([
        ['2026-10-10 09:00', local(2026, 10, 10, 9)],
        ['2026-10-10T17:45', local(2026, 10, 10, 17, 45)],
        ['2026-02-30 09:00', null],
        ['2026-10-10 24:00', null],
        ['2026-10-09 14:00', null],
        ['tomorrow', null],
    ])('parses custom input %s', (input, expected) => {
        const parsed = parseCustomSnooze(input, local(2026, 10, 9, 14, 31))
        expect(parsed?.getTime() ?? null).toBe(expected?.getTime() ?? null)
    })
})
