import { dayjs } from 'lib/dayjs'
import { dateStringToComponents, dateStringToDayJs } from 'lib/utils/dateFilters'

import { IntervalType } from '~/types'

// Bucket key format matching ClickHouse dateTrunc's DateTime output, so the zero-fill keys we
// generate line up with the query's bucket strings. One format for every interval — a day bucket
// is just midnight. Change it here, nowhere else.
export const BUCKET_FORMAT = 'YYYY-MM-DD HH:mm:ss'

// Resolve a date filter to absolute bounds. Hour/minute/second relative ranges ("-1h") roll from
// now; dateStringToDayJs anchors day+ ranges to the start of the day (the established behaviour).
export function resolveWindow(
    dateFrom: string | null,
    dateTo: string | null,
    timezone: string
): { start: dayjs.Dayjs; end: dayjs.Dayjs } {
    const now = dayjs().tz(timezone)
    const end = (dateTo ? dateStringToDayJs(dateTo, timezone) : now) ?? now
    const components = dateStringToComponents(dateFrom)
    if (components && ['hour', 'minute', 'second'].includes(components.unit) && !dateTo) {
        // components.amount is signed (negative for the past), so add() walks backwards.
        return { start: now.add(components.amount, components.unit as dayjs.ManipulateType), end: now }
    }
    const start = dateStringToDayJs(dateFrom, timezone) ?? now.subtract(7, 'day')
    return { start, end }
}

// Truncate to the start of an interval bucket the way ClickHouse's dateTrunc does, so generated keys
// line up with the query's bucket strings. dayjs' startOf covers minute/hour/day/month; only 'week'
// differs — dateTrunc('week') is ISO (Monday-start) while dayjs defaults to Sunday.
export function startOfBucket(d: dayjs.Dayjs, interval: IntervalType): dayjs.Dayjs {
    if (interval === 'week') {
        const day = d.day() // 0 = Sunday … 6 = Saturday
        return d.startOf('day').subtract((day + 6) % 7, 'day')
    }
    return d.startOf(interval)
}

// Every bucket key across the resolved window [start, end] at the active interval, formatted to match
// dateTrunc's DateTime output. Series are zero-filled against these so the x-axis spans the whole
// selected range instead of clipping to the buckets that happened to have events.
export function buildBucketKeys(
    dateFrom: string | null,
    dateTo: string | null,
    timezone: string,
    interval: IntervalType
): string[] {
    const { start, end } = resolveWindow(dateFrom, dateTo, timezone)
    const first = startOfBucket(start, interval)
    const last = startOfBucket(end, interval).valueOf()
    const keys: string[] = []
    // Re-anchor each bucket from the window start instead of cumulatively adding to a timezone-aware
    // cursor: Day.js keeps the original UTC offset across `add`, so a range crossing a DST boundary
    // would otherwise drop a bucket (short by an hour) or repeat one. startOf() re-resolves the offset
    // each step; the dedupe guards the fall-back hour that wall-clock-repeats. The cap bounds a
    // pathological range.
    for (let i = 0; i < 100000; i++) {
        const bucket = startOfBucket(first.add(i, interval), interval)
        if (bucket.valueOf() > last) {
            break
        }
        const key = bucket.format(BUCKET_FORMAT)
        if (key !== keys[keys.length - 1]) {
            keys.push(key)
        }
    }
    return keys
}

// True when the final bucket is the current, still-running interval (open-ended window), so a chart
// can dash that segment as "in progress" rather than letting the partial period read as a drop.
// Needs ≥2 buckets to have a segment to dash; `now` is injectable so the logic stays testable.
export function lastBucketIsInProgress(
    bucketKeys: string[],
    timezone: string,
    interval: IntervalType,
    now: dayjs.Dayjs = dayjs()
): boolean {
    if (bucketKeys.length < 2) {
        return false
    }
    const currentBucket = startOfBucket(now.tz(timezone), interval).format(BUCKET_FORMAT)
    return bucketKeys[bucketKeys.length - 1] === currentBucket
}

// Normalize a raw bucket string from a query (a date or datetime) to BUCKET_FORMAT so it joins the
// generated keys regardless of how ClickHouse rendered it. The value always carries the project-tz
// wall clock, in one of three shapes: naive (toString(dateTrunc)), Z-stamped (a raw DateTime
// column), or offset-stamped like 2026-07-21T00:00:00-07:00 (a typed DateTime column in a non-UTC
// project). Strip the zone designator before parsing so those digits survive verbatim: any parse
// that honors the offset re-converts a wall clock that was never an instant, shifting every bucket
// off the axis so nothing matches, which renders as a flat or empty chart. buildBucketKeys formats
// keys as the same wall clock.
export function normalizeBucket(raw: unknown): string {
    const s = String(raw ?? '')
    return s ? dayjs.utc(s.replace(/(?:Z|[+-]\d{2}:?\d{2})$/, '')).format(BUCKET_FORMAT) : ''
}

// Human-readable axis/hover label for a bucket, showing the time only when the interval is sub-day.
export function formatBucketLabel(bucket: string, interval: IntervalType): string {
    const d = dayjs(bucket)
    if (!d.isValid()) {
        return bucket
    }
    return interval === 'hour' || interval === 'minute' || interval === 'second'
        ? d.format('MMM D, HH:mm')
        : d.format('MMM D')
}
