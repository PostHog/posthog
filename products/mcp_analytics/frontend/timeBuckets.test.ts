import { dayjs } from 'lib/dayjs'

import { buildBucketKeys, formatBucketLabel, normalizeBucket } from './timeBuckets'

describe('timeBuckets', () => {
    describe('normalizeBucket', () => {
        // Guards the flat-zero-sparkline bug: whether the query serializes the bucket as a naive
        // datetime or a Z-stamped ISO, its wall-clock digits must survive verbatim — even when the
        // browser sits in a different timezone than the project — or it matches no key.
        it.each([
            ['2026-06-18 00:00:00', '2026-06-18 00:00:00'], // naive (toString(dateTrunc))
            ['2026-06-19T00:00:00Z', '2026-06-19 00:00:00'], // Z-stamped ISO (raw DateTime column)
            ['2026-06-19T00:00:00+00:00', '2026-06-19 00:00:00'],
            ['2026-06-19T11:30:00Z', '2026-06-19 11:30:00'],
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
})
