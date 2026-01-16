import { DateMappingOption } from '~/types'

import { formatDateRangeLabel, parseDateExpression } from './utils'

const TEST_TIMEZONE = 'UTC'

const TEST_DATE_OPTIONS: DateMappingOption[] = [
    { key: 'Last 1 hour', values: ['-1h'], defaultInterval: 'hour' },
    { key: 'Last 24 hours', values: ['-24h'], defaultInterval: 'hour' },
]

describe('parseDateExpression', () => {
    beforeEach(() => {
        jest.useFakeTimers()
        jest.setSystemTime(new Date('2024-01-15T12:00:00Z'))
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it.each([
        ['now', '2024-01-15T12:00:00.000Z'],
        ['NOW', '2024-01-15T12:00:00.000Z'],
        ['  now  ', '2024-01-15T12:00:00.000Z'],
    ])('parses "now" keyword: %s', (input, expected) => {
        const result = parseDateExpression(input, TEST_TIMEZONE)
        expect(result?.toISOString()).toBe(expected)
    })

    it.each([
        ['-30M', '2024-01-15T11:30:00.000Z', 'minutes'],
        ['-1h', '2024-01-15T11:00:00.000Z', 'hours'],
        ['-3h', '2024-01-15T09:00:00.000Z', 'hours'],
        ['-1d', '2024-01-14T12:00:00.000Z', 'days'],
        ['-7d', '2024-01-08T12:00:00.000Z', 'days'],
        ['-1w', '2024-01-08T12:00:00.000Z', 'weeks'],
        ['-1m', '2023-12-15T12:00:00.000Z', 'months'],
        ['-1y', '2023-01-15T12:00:00.000Z', 'years'],
        ['-1q', '2023-10-15T12:00:00.000Z', 'quarters (3 months)'],
        ['-30s', '2024-01-15T11:59:30.000Z', 'seconds'],
    ])('parses relative expression %s (%s)', (input, expected) => {
        const result = parseDateExpression(input, TEST_TIMEZONE)
        expect(result?.toISOString()).toBe(expected)
    })

    it.each([
        ['2024-01-10', '2024-01-10T00:00:00.000Z'],
        ['2024-01-10T15:30:00', '2024-01-10T15:30:00.000Z'],
        ['2024-01-10 15:30', '2024-01-10T15:30:00.000Z'],
    ])('parses absolute date %s', (input, expected) => {
        const result = parseDateExpression(input, TEST_TIMEZONE)
        expect(result?.toISOString()).toBe(expected)
    })

    it.each([
        ['2024-01-10T15:00:00.000Z', 'UTC', '15:00'],
        ['2024-01-10T15:00:00.000Z', 'America/New_York', '10:00'],
        ['2024-01-10T15:00:00.000Z', 'Europe/London', '15:00'],
        ['2024-01-10T15:00:00.000Z', 'Asia/Tokyo', '00:00'],
        ['2024-01-10T15:00:00+02:00', 'UTC', '13:00'],
        ['2024-01-10T15:00:00-05:00', 'UTC', '20:00'],
    ])('converts ISO string %s to timezone %s showing %s', (input, timezone, expectedTime) => {
        const result = parseDateExpression(input, timezone)
        expect(result?.format('HH:mm')).toBe(expectedTime)
    })

    it.each([['invalid'], [''], ['abc123'], ['--1h'], ['1h']])('returns null for invalid expression: %s', (input) => {
        const result = parseDateExpression(input, TEST_TIMEZONE)
        expect(result).toBeNull()
    })
})

describe('formatDateRangeLabel', () => {
    beforeEach(() => {
        jest.useFakeTimers()
        jest.setSystemTime(new Date('2024-01-15T12:00:00Z'))
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it('returns matching option key when date matches', () => {
        const result = formatDateRangeLabel({ date_from: '-1h', date_to: null }, TEST_TIMEZONE, TEST_DATE_OPTIONS)
        expect(result).toBe('Last 1 hour')
    })

    it('formats absolute date range', () => {
        const result = formatDateRangeLabel(
            { date_from: '2024-01-10T10:00:00Z', date_to: '2024-01-15T12:00:00Z' },
            TEST_TIMEZONE,
            TEST_DATE_OPTIONS
        )
        expect(result).toBe('2024-01-10 10:00 - 2024-01-15 12:00')
    })

    it('uses current time when date_to is null and no option matches', () => {
        const result = formatDateRangeLabel({ date_from: '2024-01-10T10:00:00Z', date_to: null }, TEST_TIMEZONE, [])
        expect(result).toBe('2024-01-10 10:00 - 2024-01-15 12:00')
    })

    it('returns default message when date_from is empty', () => {
        const result = formatDateRangeLabel({ date_from: '', date_to: null }, TEST_TIMEZONE, TEST_DATE_OPTIONS)
        expect(result).toBe('Select date range')
    })

    it.each([
        ['UTC', '2024-01-10 15:00 - 2024-01-15 12:00'],
        ['America/New_York', '2024-01-10 10:00 - 2024-01-15 07:00'],
        ['Asia/Tokyo', '2024-01-11 00:00 - 2024-01-15 21:00'],
    ])('updates label when timezone changes to %s', (timezone, expectedLabel) => {
        const result = formatDateRangeLabel(
            { date_from: '2024-01-10T15:00:00.000Z', date_to: '2024-01-15T12:00:00.000Z' },
            timezone,
            TEST_DATE_OPTIONS
        )
        expect(result).toBe(expectedLabel)
    })
})
