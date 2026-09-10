import { dayjs } from 'lib/dayjs'

import { DateRange } from '~/queries/schema/schema-general'
import { LogsSettings } from '~/types'

import { DEFAULT_LOGS_RETENTION_DAYS, logsRangeBeyondRetention, resolveLogsRetentionDays } from './logsRetentionWindow'

// Ranges are written relative to now, so no case expires as the real clock moves.
const daysAgo = (days: number): string => dayjs().subtract(days, 'days').toISOString()

describe('logsRetentionWindow', () => {
    it.each<[string, LogsSettings | null | undefined, number]>([
        ['a paid 30-day tier', { retention_days: 30 }, 30],
        ['the default tier', { retention_days: 14 }, 14],
        ['settings without a retention key', {}, DEFAULT_LOGS_RETENTION_DAYS],
        ['no settings at all', null, DEFAULT_LOGS_RETENTION_DAYS],
        ['settings still loading', undefined, DEFAULT_LOGS_RETENTION_DAYS],
        ['a nonsense stored value', { retention_days: 0 }, DEFAULT_LOGS_RETENTION_DAYS],
    ])('resolves retention for %s', (_label, logsSettings, expected) => {
        expect(resolveLogsRetentionDays(logsSettings)).toEqual(expected)
    })

    it.each<[string, DateRange, number, boolean | null]>([
        ['a relative range inside the window', { date_from: '-1h', date_to: null }, 14, null],
        ['a relative range up to the window edge', { date_from: '-7d', date_to: null }, 14, null],
        ['a relative range past the window', { date_from: '-30d', date_to: null }, 14, false],
        // The report's case: raising retention to 30 days stops warning about a 20-day range.
        ['a 20-day range on the 30-day tier', { date_from: '-20d', date_to: null }, 30, null],
        ['a 20-day range on the 14-day tier', { date_from: '-20d', date_to: null }, 14, false],
        ['an absolute range wholly before the window', { date_from: daysAgo(60), date_to: daysAgo(40) }, 14, true],
        ['an absolute range straddling the window', { date_from: daysAgo(60), date_to: daysAgo(2) }, 14, false],
        // The query runner defaults a missing start to a window inside every retention tier.
        ['a missing start', { date_from: null, date_to: null }, 14, null],
        ['an unparseable start', { date_from: 'last tuesday-ish', date_to: null }, 14, null],
        // The API accepts `-1mEnd`, which the picker's parser does not read, so the end is unknown.
        ['an unparseable end', { date_from: '-90d', date_to: '-1mEnd' }, 14, null],
    ])('reports %s', (_label, dateRange, retentionDays, expectedCoversWholeRange) => {
        const window = logsRangeBeyondRetention(dateRange, retentionDays, 'UTC')

        if (expectedCoversWholeRange === null) {
            expect(window).toBeNull()
            return
        }
        expect(window).not.toBeNull()
        expect(window?.coversWholeRange).toEqual(expectedCoversWholeRange)
        expect(window?.retentionDays).toEqual(retentionDays)
        expect(dayjs().diff(window?.start, 'days')).toEqual(retentionDays)
    })
})
