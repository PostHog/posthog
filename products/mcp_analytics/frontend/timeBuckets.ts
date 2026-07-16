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
    const last = startOfBucket(end, interval).valueOf()
    const keys: string[] = []
    let cursor = startOfBucket(start, interval)
    // Bounded windows keep this small; the cap is just a guard against a pathological range.
    for (let i = 0; cursor.valueOf() <= last && i < 100000; i++) {
        keys.push(cursor.format(BUCKET_FORMAT))
        cursor = cursor.add(1, interval)
    }
    return keys
}

// Normalize a raw bucket string from a query (a date or datetime) to BUCKET_FORMAT so it joins the
// generated keys regardless of how ClickHouse rendered it. The raw value is a project-timezone wall
// clock (dateTrunc runs in the team timezone), so parse it AS that timezone — `dayjs(s).tz(tz)` would
// read it in the browser tz and then convert, shifting day buckets off midnight so nothing matches
// and the chart reads flat zero for anyone not sitting in the project timezone.
export function normalizeBucket(raw: unknown, timezone: string): string {
    const s = String(raw ?? '')
    return s ? dayjs.tz(s, timezone).format(BUCKET_FORMAT) : ''
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
