import {
    LogsFilterPreviewPoint,
    SPARKLINE_ROW_LIMIT,
    formatBytes,
} from 'products/logs/frontend/components/LogsFilterPreview/logsFilterVolumePreview'

const SECONDS_PER_DAY = 86400

export interface RetentionStorageProjection {
    totalBytes: number
    /** Actual span the preview covers, derived from the data rather than assumed to be 24h. */
    windowSeconds: number
    bytesPerDay: number
    /** What the rule holds once every day in the retention window is populated. */
    retainedBytes: number
    /** The preview hit the backend row cap, so the newest buckets are missing and this is an undercount. */
    truncated: boolean
}

/**
 * Project how much storage a retention rule would hold, from the volume its filter matched
 * over the previewed window.
 *
 * The window is deliberately derived from the returned buckets instead of being assumed to be
 * exactly 24h: the sparkline query floors `now - 24h` to the bucket interval, so it really covers
 * 24h plus up to one bucket, and the trailing bucket is only partially elapsed. Measuring
 * `now - firstBucket` is self-correcting — the partial bucket contributes partial bytes *and*
 * partial span — and it survives a change to the backend's bucket sizing.
 */
export function buildRetentionProjection(
    points: LogsFilterPreviewPoint[] | null,
    retentionDays: number,
    nowMs: number = Date.now()
): RetentionStorageProjection | null {
    if (!points || points.length === 0) {
        return null
    }

    let totalBytes = 0
    const bucketTimes: number[] = []
    const seenTimes = new Set<string>()
    for (const point of points) {
        totalBytes += point.bytes_uncompressed ?? 0
        if (!seenTimes.has(point.time)) {
            seenTimes.add(point.time)
            bucketTimes.push(new Date(point.time).getTime())
        }
    }

    const truncated = points.length >= SPARKLINE_ROW_LIMIT
    const firstBucketMs = Math.min(...bucketTimes)
    const lastBucketMs = Math.max(...bucketTimes)
    const bucketSeconds = bucketTimes.length >= 2 ? (bucketTimes[1] - bucketTimes[0]) / 1000 : 0

    // When rows were dropped by the row cap, `now` is no longer the end of the data we got back,
    // so measure to the end of the last bucket we actually received instead.
    let windowSeconds = truncated
        ? (lastBucketMs - firstBucketMs) / 1000 + bucketSeconds
        : (nowMs - firstBucketMs) / 1000
    if (!Number.isFinite(windowSeconds) || windowSeconds <= 0 || bucketSeconds <= 0) {
        // A single bucket gives us no interval to reason about — fall back to treating the
        // response as one day rather than dividing by ~0 and reporting an absurd rate.
        windowSeconds = SECONDS_PER_DAY
    }

    const bytesPerDay = (totalBytes * SECONDS_PER_DAY) / windowSeconds
    return {
        totalBytes,
        windowSeconds,
        bytesPerDay,
        retainedBytes: bytesPerDay * retentionDays,
        truncated,
    }
}

export function retentionProjectionText(projection: RetentionStorageProjection, retentionDays: number): string {
    if (projection.totalBytes === 0) {
        return "No logs matched these filters in the last 24 hours, so this rule wouldn't store anything today."
    }
    const base =
        `Based on the last 24 hours, this rule would store ~${formatBytes(projection.bytesPerDay)}/day ` +
        `for ${retentionDays} days (~${formatBytes(projection.retainedBytes)} retained at steady state).`
    return projection.truncated ? `${base} The preview hit its row limit, so actual volume may be higher.` : base
}
