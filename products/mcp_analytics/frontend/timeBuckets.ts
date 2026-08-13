import { dayjs } from 'lib/dayjs'
import { dateStringToComponents, dateStringToDayJs, getDefaultInterval } from 'lib/utils/dateFilters'

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

// Grouping intervals offered in the picker. Sub-hour intervals are left out: the date filter has no
// minute-level quick range, and a window short enough to need one is rare enough to skip.
export const SELECTABLE_INTERVALS: IntervalType[] = ['hour', 'day', 'week', 'month']

const INTERVAL_LABELS: Record<string, string> = { hour: 'Hour', day: 'Day', week: 'Week', month: 'Month' }

// A line this dense is already a smear, and MCPToolQualityDailyStatsQuery's row limit starts dropping
// the newest buckets not far above it, so intervals past this many points are offered disabled.
const MAX_BUCKETS = 1000

export interface IntervalOption {
    value: IntervalType
    label: string
    // Set when the interval doesn't suit the selected window — the picker offers it disabled with
    // this as the reason.
    disabledReason: string | null
}

// Read a pinned grouping interval off a URL param, ignoring anything the picker can't offer.
export function parseIntervalParam(raw: unknown): IntervalType | null {
    return SELECTABLE_INTERVALS.find((interval) => interval === raw) ?? null
}

// How many buckets a window spans at an interval, without materializing every key. Approximate by
// design: month lengths and DST shifts move the count by one, which never changes the judgement it
// feeds.
export function approximateBucketCount(
    dateFrom: string | null,
    dateTo: string | null,
    timezone: string,
    interval: IntervalType
): number {
    const { start, end } = resolveWindow(dateFrom, dateTo, timezone)
    return Math.max(1, Math.floor(end.diff(startOfBucket(start, interval), interval, true)) + 1)
}

// The picker's options for a window, with the intervals that would draw an unreadable line or
// collapse the range to a single point marked disabled.
export function intervalOptionsForWindow(
    dateFrom: string | null,
    dateTo: string | null,
    timezone: string
): IntervalOption[] {
    return SELECTABLE_INTERVALS.map((value) => {
        const buckets = approximateBucketCount(dateFrom, dateTo, timezone, value)
        return {
            value,
            label: INTERVAL_LABELS[value] ?? value,
            disabledReason: buckets > MAX_BUCKETS ? 'Range too long' : buckets < 2 ? 'Range too short' : null,
        }
    })
}

// The interval to group by: the pinned choice when it still suits the window, else PostHog's
// auto-choice for the range. A pin survives date changes, so it has to give way when the window
// outgrows it — hourly kept from a 12-hour window would otherwise chart a year hour by hour.
export function resolveInterval(
    dateFrom: string | null,
    dateTo: string | null,
    timezone: string,
    pinned: IntervalType | null
): IntervalType {
    if (pinned) {
        const option = intervalOptionsForWindow(dateFrom, dateTo, timezone).find((o) => o.value === pinned)
        if (option && !option.disabledReason) {
            return pinned
        }
    }
    return getDefaultInterval(dateFrom, dateTo)
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
