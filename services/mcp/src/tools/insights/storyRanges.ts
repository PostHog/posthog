const UNIT_MS: Record<string, number> = {
    second: 1_000,
    minute: 60_000,
    hour: 3_600_000,
    day: 86_400_000,
    week: 7 * 86_400_000,
}

// Agents copy dates in several shapes: `2026-10-02`, `2026-10-02 14:00:00`, `2026-10-02T14:00:00Z`.
function pointKey(value: string): string {
    return value
        .trim()
        .replace('T', ' ')
        .replace(/(\.\d+)?(Z|[+-]\d{2}:?\d{2})$/, '')
}

// A day matches every hour in it, and an hour matches the day it falls on.
function sameMoment(key: string, date: string): boolean {
    const length = Math.min(key.length, date.length)
    return key.slice(0, length) === date.slice(0, length)
}

function lastIndexWhere(keys: string[], test: (key: string) => boolean): number {
    for (let index = keys.length - 1; index >= 0; index--) {
        if (test(keys[index]!)) {
            return index
        }
    }
    return -1
}

/** The point's wall-clock time as if it were UTC. Labels carry no zone, so this keeps their calendar fields intact. */
function naiveMs(key: string): number | null {
    const match = /^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2})(?::(\d{2}))?)?/.exec(key)
    if (!match) {
        return null
    }
    const [, year, month, day, hour, minute, second] = match
    return Date.UTC(
        Number(year),
        Number(month) - 1,
        Number(day),
        Number(hour ?? 0),
        Number(minute ?? 0),
        Number(second ?? 0)
    )
}

/** When the bucket that starts at `key` ends, on the same naive clock. */
function bucketEndMs(key: string, interval: string): number | null {
    const start = naiveMs(key)
    if (start === null) {
        return null
    }
    const date = new Date(start)
    if (interval === 'month') {
        return Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + 1, 1)
    }
    if (interval === 'quarter') {
        return Date.UTC(date.getUTCFullYear(), Math.floor(date.getUTCMonth() / 3) * 3 + 3, 1)
    }
    if (interval === 'year') {
        return Date.UTC(date.getUTCFullYear() + 1, 0, 1)
    }
    return start + (UNIT_MS[interval] ?? UNIT_MS.day!)
}

const CALENDAR_INTERVALS = new Set(['week', 'month', 'quarter', 'year'])

function startIndex(keys: string[], date: string, interval: string): number | null {
    const exact = keys.findIndex((key) => sameMoment(key, date))
    if (exact !== -1) {
        return exact
    }
    if (date < keys[0]!) {
        return 0
    }
    if (!CALENDAR_INTERVALS.has(interval)) {
        return null
    }
    // On a weekly or longer chart, a date falls in the bucket that starts before it.
    const containing = lastIndexWhere(keys, (key) => key < date)
    const end = bucketEndMs(keys[containing]!, interval)
    const dateMs = naiveMs(date)
    const isPastLastBucket = containing === keys.length - 1 && (end === null || dateMs === null || dateMs >= end)
    return isPastLastBucket ? null : containing
}

function endIndex(keys: string[], date: string): number | null {
    const exact = lastIndexWhere(keys, (key) => sameMoment(key, date))
    if (exact !== -1) {
        return exact
    }
    const containing = lastIndexWhere(keys, (key) => key < date)
    return containing === -1 ? null : containing
}

/** The inclusive range of points that a chapter's dates cover, or null when they cover none of the chart. */
export function findStoryRange(days: string[], interval: string, start: string, end?: string): [number, number] | null {
    if (!days.length) {
        return null
    }
    const keys = days.map(pointKey)
    const first = startIndex(keys, pointKey(start), interval)
    const last = endIndex(keys, pointKey(end ?? start))
    if (first === null || last === null || last < first) {
        return null
    }
    return [first, last]
}

function zoneOffsetMs(timezone: string, utcMs: number): number {
    try {
        const name = new Intl.DateTimeFormat('en-US', { timeZone: timezone, timeZoneName: 'longOffset' })
            .formatToParts(new Date(utcMs))
            .find((part) => part.type === 'timeZoneName')?.value
        const match = /GMT([+-])(\d{2}):?(\d{2})?/.exec(name ?? '')
        if (!match) {
            return 0
        }
        return (match[1] === '-' ? -1 : 1) * (Number(match[2]) * 60 + Number(match[3] ?? 0)) * 60_000
    } catch {
        return 0
    }
}

export function lastBucketInProgress(days: string[], interval: string, timezone = 'UTC', now = Date.now()): boolean {
    const last = days[days.length - 1]
    const end = last === undefined ? null : bucketEndMs(pointKey(last), interval)
    if (end === null) {
        return false
    }
    // The offset belongs to the instant the bucket ends, which a second lookup finds across a daylight-saving change.
    const guess = end - zoneOffsetMs(timezone, end)
    return end - zoneOffsetMs(timezone, guess) > now
}
