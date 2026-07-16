import { dayjs } from 'lib/dayjs'

import { buildBucketKeys, formatBucketLabel, normalizeBucket } from './timeBuckets'

describe('timeBuckets', () => {
    describe('normalizeBucket', () => {
        it('reads the bucket in the project timezone, not the browser tz, so day buckets stay at midnight', () => {
            // The browser sits in a different tz than the project (UTC here). Parsing the raw string in
            // the browser tz and converting would push the bucket off midnight and it would match no
            // key — the flat-zero-sparkline bug. Guard: the wall clock must survive unchanged.
            dayjs.tz.setDefault('Europe/Athens')
            try {
                expect(normalizeBucket('2026-06-18 00:00:00', 'UTC')).toBe('2026-06-18 00:00:00')
            } finally {
                dayjs.tz.setDefault('UTC')
            }
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

        it('spans a short window at minute granularity', () => {
            expect(buildBucketKeys('2026-06-01T09:00:00Z', '2026-06-01T09:04:00Z', 'UTC', 'minute')).toEqual([
                '2026-06-01 09:00:00',
                '2026-06-01 09:01:00',
                '2026-06-01 09:02:00',
                '2026-06-01 09:03:00',
                '2026-06-01 09:04:00',
            ])
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
