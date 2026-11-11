import { getCalendars } from 'expo-localization'

import { formatClock } from './dates'

afterEach(() => {
    jest.restoreAllMocks()
    jest.mocked(getCalendars).mockReturnValue([{ ...getCalendars()[0], uses24hourClock: false }])
})

test.each<[boolean, number, number, string]>([
    [false, 0, 3, '12:03 AM'],
    [false, 9, 5, '9:05 AM'],
    [false, 12, 0, '12:00 PM'],
    [false, 16, 7, '4:07 PM'],
    [true, 0, 3, '00:03'],
    [true, 9, 5, '09:05'],
    [true, 12, 0, '12:00'],
    [true, 16, 7, '16:07'],
])('formatClock with 24-hour preference %s at %s:%s returns %s', (uses24hourClock, hour, minute, expected) => {
    jest.mocked(getCalendars).mockReturnValue([{ ...getCalendars()[0], uses24hourClock }])
    expect(formatClock(new Date(2026, 9, 13, hour, minute))).toBe(expected)
})

test.each([
    [true, '4:07 PM'],
    [false, '16:07'],
])('formatClock falls back to the browser hour12 preference %s', (hour12, expected) => {
    jest.mocked(getCalendars).mockReturnValue([{ ...getCalendars()[0], uses24hourClock: null }])
    const options = new Intl.DateTimeFormat().resolvedOptions()
    jest.spyOn(Intl.DateTimeFormat.prototype, 'resolvedOptions').mockReturnValue({ ...options, hour12 })
    expect(formatClock(new Date(2026, 9, 13, 16, 7))).toBe(expected)
})

test('formatClock reads a changed device preference on the next call', () => {
    const date = new Date(2026, 9, 13, 16, 7)
    expect(formatClock(date)).toBe('4:07 PM')
    jest.mocked(getCalendars).mockReturnValue([{ ...getCalendars()[0], uses24hourClock: true }])
    expect(formatClock(date)).toBe('16:07')
})
