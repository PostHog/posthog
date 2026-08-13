import { dayjs } from 'lib/dayjs'

import { IntervalType } from '~/types'

import {
    buildBucketKeys,
    formatBucketLabel,
    intervalOptionsForWindow,
    lastBucketIsInProgress,
    normalizeBucket,
    resolveInterval,
} from './timeBuckets'

describe('timeBuckets', () => {
    describe('normalizeBucket', () => {
        // Guards the flat-zero-sparkline bug: however the query serializes the bucket, its
        // wall-clock digits must survive verbatim, even when the browser sits in a different
        // timezone than the project, or it matches no key.
        it.each([
            ['2026-06-18 00:00:00', '2026-06-18 00:00:00'], // naive (toString(dateTrunc))
            ['2026-06-19T00:00:00Z', '2026-06-19 00:00:00'], // Z-stamped ISO (raw DateTime column)
            ['2026-06-19T00:00:00+00:00', '2026-06-19 00:00:00'],
            ['2026-06-19T11:30:00Z', '2026-06-19 11:30:00'],
            ['2026-06-19T00:00:00-07:00', '2026-06-19 00:00:00'], // offset-stamped (typed DateTime, non-UTC project)
        ])('keeps %s as %s under a non-UTC browser tz', (raw, expected) => {
            dayjs.tz.setDefault('Europe/Athens')
            try {
                expect(normalizeBucket(raw)).toBe(expected)
            } finally {
                dayjs.tz.setDefault('UTC')
            }
        })

        it('returns empty string for missing values', () => {
            expect(normalizeBucket(null)).toBe('')
            expect(normalizeBucket('')).toBe('')
        })
    })

    describe('buildBucketKeys', () => {
        it('spans an absolute window at hour granularity, inclusive of both ends', () => {
            expect(buildBucketKeys('2026-06-01T00:00:00Z', '2026-06-01T03:00:00Z', 'UTC', 'hour')).toEqual([
                '2026-06-01 00:00:00',
                '2026-06-01 01:00:00',
                '2026-06-01 02:00:00',
                '2026-06-01 03:00:00',
            ])
        })

        it('emits one key per day across a relative window, including empty trailing days', () => {
            jest.useFakeTimers().setSystemTime(new Date('2026-06-18T12:00:00Z'))
            try {
                expect(buildBucketKeys('-7d', null, 'UTC', 'day')).toEqual([
                    '2026-06-11 00:00:00',
                    '2026-06-12 00:00:00',
                    '2026-06-13 00:00:00',
                    '2026-06-14 00:00:00',
                    '2026-06-15 00:00:00',
                    '2026-06-16 00:00:00',
                    '2026-06-17 00:00:00',
                    '2026-06-18 00:00:00',
                ])
            } finally {
                jest.useRealTimers()
            }
        })

        it('truncates weekly buckets to ISO Monday starts (matching ClickHouse dateTrunc)', () => {
            // 2026-06-01 is a Monday; every key should land on a Monday.
            expect(buildBucketKeys('2026-06-01', '2026-06-21', 'UTC', 'week')).toEqual([
                '2026-06-01 00:00:00',
                '2026-06-08 00:00:00',
                '2026-06-15 00:00:00',
            ])
        })

        // Guards the DST data-drop: cumulative add on a tz-aware cursor keeps the pre-DST offset and
        // lands short after spring-forward, dropping the last day. Re-anchoring keeps every bucket.
        it('spans a daily window crossing a spring-forward DST boundary without dropping a bucket', () => {
            expect(buildBucketKeys('2026-03-07', '2026-03-09', 'America/New_York', 'day')).toEqual([
                '2026-03-07 00:00:00',
                '2026-03-08 00:00:00',
                '2026-03-09 00:00:00',
            ])
        })

        it('spans a short window at minute granularity', () => {
            expect(buildBucketKeys('2026-06-01T09:00:00Z', '2026-06-01T09:04:00Z', 'UTC', 'minute')).toEqual([
                '2026-06-01 09:00:00',
                '2026-06-01 09:01:00',
                '2026-06-01 09:02:00',
                '2026-06-01 09:03:00',
                '2026-06-01 09:04:00',
            ])
        })

        it('produces keys a normalized query bucket lands on', () => {
            jest.useFakeTimers().setSystemTime(new Date('2026-06-18T12:00:00Z'))
            try {
                const keys = buildBucketKeys('-7d', null, 'UTC', 'day')
                expect(keys).toContain(normalizeBucket('2026-06-18T00:00:00Z'))
            } finally {
                jest.useRealTimers()
            }
        })
    })

    describe('formatBucketLabel', () => {
        it('shows the time for sub-day intervals and the date otherwise', () => {
            expect(formatBucketLabel('2026-06-01 09:30:00', 'minute')).toBe('Jun 1, 09:30')
            expect(formatBucketLabel('2026-06-01 09:00:00', 'hour')).toBe('Jun 1, 09:00')
            expect(formatBucketLabel('2026-06-01 00:00:00', 'day')).toBe('Jun 1')
        })
    })

    describe('lastBucketIsInProgress', () => {
        const tz = 'UTC'
        const keys = ['2026-06-27 00:00:00', '2026-06-28 00:00:00', '2026-06-29 00:00:00']

        it('flags the tail when the last bucket is the interval containing now', () => {
            const now = dayjs.tz('2026-06-29 09:15:00', tz)
            expect(lastBucketIsInProgress(keys, tz, 'day', now)).toBe(true)
        })

        it('leaves the tail solid when the window ends in the past', () => {
            const now = dayjs.tz('2026-07-05 09:15:00', tz)
            expect(lastBucketIsInProgress(keys, tz, 'day', now)).toBe(false)
        })

        it('does not dash when there is no segment to dash', () => {
            const now = dayjs.tz('2026-06-29 09:15:00', tz)
            expect(lastBucketIsInProgress(['2026-06-29 00:00:00'], tz, 'day', now)).toBe(false)
            expect(lastBucketIsInProgress([], tz, 'day', now)).toBe(false)
        })

        // The project timezone decides which bucket "now" falls in: at 23:15 UTC on the 29th it is
        // already the 30th in Athens, so a window ending on the 29th is settled there but still
        // collecting in UTC. Reading the browser's zone instead would dash the wrong tail.
        it('resolves the current bucket in the project timezone, not the browser', () => {
            const now = dayjs.tz('2026-06-29 23:15:00', tz)
            expect(lastBucketIsInProgress(keys, tz, 'day', now)).toBe(true)
            expect(lastBucketIsInProgress(keys, 'Europe/Athens', 'day', now)).toBe(false)
        })
    })

    describe('resolveInterval', () => {
        // A pin outlives the window it was set on, so it has to give way once the window outgrows it:
        // charting a year hour by hour also runs past the query's row limit, which drops the newest
        // buckets. A pin that still fits has to beat the auto-choice — that's the point of pinning.
        it.each([
            ['-14d', 'hour', 'hour'], // 337 hourly buckets: fits
            ['-1y', 'hour', 'month'], // 8761 hourly buckets: back to the auto-choice
            ['-7d', 'month', 'day'], // shorter than one month: back to the auto-choice
            ['-1y', 'day', 'day'], // 367 daily buckets: fits, and beats the auto-choice
            ['-1y', null, 'month'], // nothing pinned: the auto-choice
        ])('groups a %s window pinned to %s by %s', (dateFrom, pinned, expected) => {
            expect(resolveInterval(dateFrom, null, 'UTC', pinned as IntervalType | null)).toBe(expected)
        })
    })

    describe('intervalOptionsForWindow', () => {
        it('disables the intervals that would smear or collapse the window', () => {
            expect(intervalOptionsForWindow('-1y', null, 'UTC')).toEqual([
                { value: 'hour', label: 'Hour', disabledReason: 'Range too long' },
                { value: 'day', label: 'Day', disabledReason: null },
                { value: 'week', label: 'Week', disabledReason: null },
                { value: 'month', label: 'Month', disabledReason: null },
            ])
            expect(intervalOptionsForWindow('-7d', null, 'UTC')).toEqual([
                { value: 'hour', label: 'Hour', disabledReason: null },
                { value: 'day', label: 'Day', disabledReason: null },
                { value: 'week', label: 'Week', disabledReason: null },
                { value: 'month', label: 'Month', disabledReason: 'Range too short' },
            ])
        })
    })
})
