import { LogsFilterPreviewPoint } from 'products/logs/frontend/components/LogsFilterPreview/logsFilterVolumePreview'

import { buildRetentionProjection, retentionProjectionText } from './retentionStorageProjection'

const HALF_HOUR_MS = 30 * 60 * 1000
const GB = 1_000_000_000

/** 48 half-hour buckets ending at `lastBucketMs`, splitting `totalBytes` evenly between them. */
const buckets = (lastBucketMs: number, totalBytes: number, count = 48): LogsFilterPreviewPoint[] =>
    Array.from({ length: count }, (_, i) => ({
        time: new Date(lastBucketMs - (count - 1 - i) * HALF_HOUR_MS).toISOString(),
        service: 'api',
        count: 10,
        bytes_uncompressed: totalBytes / count,
    }))

describe('buildRetentionProjection', () => {
    it('projects bytes/day and the steady-state retained total from a full 24h window', () => {
        const lastBucketMs = Date.UTC(2026, 7, 4, 12, 0, 0)
        // First bucket is 47 half-hours before the last; `now` is the end of the last bucket,
        // so the window is exactly 24h.
        const nowMs = lastBucketMs + HALF_HOUR_MS
        const projection = buildRetentionProjection(buckets(lastBucketMs, 15 * GB), 30, nowMs)!

        expect(projection.windowSeconds).toEqual(86400)
        expect(projection.bytesPerDay).toBeCloseTo(15 * GB, -3)
        expect(projection.retainedBytes).toBeCloseTo(30 * 15 * GB, -3)
        expect(projection.truncated).toBe(false)
    })

    it('divides by the real window when the backend floors date_from past 24h', () => {
        // The sparkline query floors `now - 24h` to the bucket interval, so at 12:29 the window
        // starts at 12:00 the previous day — 49 buckets spanning 24h29m. Assuming 86400s would
        // over-project the daily rate by ~2%.
        const lastBucketMs = Date.UTC(2026, 7, 4, 12, 0, 0)
        const nowMs = lastBucketMs + 29 * 60 * 1000
        const projection = buildRetentionProjection(buckets(lastBucketMs, 15 * GB, 49), 30, nowMs)!

        expect(projection.windowSeconds).toEqual(88140)
        expect(projection.bytesPerDay).toBeLessThan(15 * GB)
        expect(projection.bytesPerDay).toBeCloseTo((15 * GB * 86400) / 88140, -3)
    })

    it('measures to the end of the last received bucket when the row cap truncated the response', () => {
        const lastBucketMs = Date.UTC(2026, 7, 4, 6, 0, 0)
        // Row cap hit, so `now` is hours past the newest bucket we got back — using it would
        // stretch the window and understate the daily rate.
        const nowMs = Date.UTC(2026, 7, 4, 12, 0, 0)
        const points = buckets(lastBucketMs, 10 * GB, 1000)
        const projection = buildRetentionProjection(points, 14, nowMs)!

        expect(projection.truncated).toBe(true)
        expect(projection.windowSeconds).toEqual(1000 * 1800)
        expect(retentionProjectionText(projection, 14)).toContain('actual volume may be higher')
    })

    it('falls back to a one-day window when only one bucket came back', () => {
        const projection = buildRetentionProjection(
            [{ time: '2026-08-04T12:00:00Z', service: 'api', count: 1, bytes_uncompressed: 5 * GB }],
            30,
            Date.UTC(2026, 7, 4, 12, 1, 0)
        )!

        expect(projection.windowSeconds).toEqual(86400)
        expect(projection.bytesPerDay).toEqual(5 * GB)
    })

    it('returns null when there is nothing to project from', () => {
        expect(buildRetentionProjection(null, 30)).toBeNull()
        expect(buildRetentionProjection([], 30)).toBeNull()
    })

    it('scales the retained total with the tier but not the daily rate', () => {
        const lastBucketMs = Date.UTC(2026, 7, 4, 12, 0, 0)
        const nowMs = lastBucketMs + HALF_HOUR_MS
        const points = buckets(lastBucketMs, 15 * GB)

        const fourteen = buildRetentionProjection(points, 14, nowMs)!
        const thirty = buildRetentionProjection(points, 30, nowMs)!

        expect(thirty.bytesPerDay).toEqual(fourteen.bytesPerDay)
        expect(thirty.retainedBytes / fourteen.retainedBytes).toBeCloseTo(30 / 14)
    })
})

describe('retentionProjectionText', () => {
    it('reads as a storage projection naming the tier', () => {
        const lastBucketMs = Date.UTC(2026, 7, 4, 12, 0, 0)
        const projection = buildRetentionProjection(buckets(lastBucketMs, 15 * GB), 30, lastBucketMs + HALF_HOUR_MS)!

        expect(retentionProjectionText(projection, 30)).toEqual(
            'Based on the last 24 hours, this rule would store ~15.00 GB/day for 30 days (~450.00 GB retained at steady state).'
        )
    })

    it('says nothing would be stored when rows came back with no bytes', () => {
        const projection = buildRetentionProjection(
            [
                { time: '2026-08-04T11:30:00Z', service: '', count: 0 },
                { time: '2026-08-04T12:00:00Z', service: '', count: 0 },
            ],
            30,
            Date.UTC(2026, 7, 4, 12, 30, 0)
        )!

        expect(projection.totalBytes).toEqual(0)
        expect(retentionProjectionText(projection, 30)).toEqual(
            "No logs matched these filters in the last 24 hours, so this rule wouldn't store anything today."
        )
    })
})
