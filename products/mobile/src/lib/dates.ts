// Written by hand instead of with Intl so the output is identical in Hermes, the web build and Jest.

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'] as const
const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'] as const
const FULL_WEEKDAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'] as const

const MINUTE = 60_000
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR

export function formatClock(date: Date): string {
    const hours = date.getHours()
    const minutes = date.getMinutes()
    const hour12 = hours % 12 === 0 ? 12 : hours % 12
    const suffix = hours < 12 ? 'AM' : 'PM'
    return `${hour12}:${String(minutes).padStart(2, '0')} ${suffix}`
}

export function formatMonthDay(date: Date): string {
    return `${MONTHS[date.getMonth()]} ${date.getDate()}`
}

export function weekdayName(date: Date): string {
    return WEEKDAYS[date.getDay()] ?? ''
}

export function fullWeekdayName(date: Date): string {
    return FULL_WEEKDAYS[date.getDay()] ?? ''
}

export function calendarDaysBetween(from: Date, to: Date): number {
    const a = new Date(from.getFullYear(), from.getMonth(), from.getDate())
    const b = new Date(to.getFullYear(), to.getMonth(), to.getDate())
    return Math.round((b.getTime() - a.getTime()) / DAY)
}

export function formatRelativeAgo(iso: string, now: Date): string {
    const date = new Date(iso)
    const diff = now.getTime() - date.getTime()
    if (diff < MINUTE) {
        return 'Just now'
    }
    if (diff < HOUR) {
        return `${Math.floor(diff / MINUTE)}m ago`
    }
    if (diff < DAY) {
        return `${Math.floor(diff / HOUR)}h ago`
    }
    if (diff < 7 * DAY) {
        return `${Math.floor(diff / DAY)}d ago`
    }
    return formatMonthDay(date)
}

export function formatActivityTime(iso: string, now: Date): string {
    const date = new Date(iso)
    const diff = now.getTime() - date.getTime()
    if (diff >= 0 && diff < MINUTE) {
        return 'Just now'
    }
    const days = calendarDaysBetween(date, now)
    if (days === 0) {
        return `Today ${formatClock(date)}`
    }
    if (days > 0 && days <= 7) {
        return `${weekdayName(date)} ${formatClock(date)}`
    }
    return `${formatMonthDay(date)}, ${formatClock(date)}`
}

/** The local calendar day as `YYYY-MM-DD`, the form a trends response gives daily buckets. */
export function isoDay(date: Date): string {
    const month = String(date.getMonth() + 1).padStart(2, '0')
    const day = String(date.getDate()).padStart(2, '0')
    return `${date.getFullYear()}-${month}-${day}`
}

export function dailyBuckets(end: Date, count: number): string[] {
    return Array.from({ length: count }, (_, index) => {
        const day = new Date(end.getFullYear(), end.getMonth(), end.getDate() - (count - 1 - index))
        return isoDay(day)
    })
}

const BUCKET_START = /^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2})(?::(\d{2}))?)?$/

/**
 * Epoch ms for a trends bucket label. A bare `YYYY-MM-DD` or a `YYYY-MM-DD HH:mm:ss` without an offset is wall-clock
 * time, so it parses as local time: `Date.parse` reads a bare date as UTC midnight, which is the day before west of
 * UTC. Anything else, such as a full ISO string with an offset, goes to `Date.parse`. NaN when it cannot be read.
 */
export function parseBucketStart(at: string): number {
    const match = BUCKET_START.exec(at)
    if (!match) {
        return Date.parse(at)
    }
    const [, year, month, day, hours, minutes, seconds] = match
    return new Date(
        Number(year),
        Number(month) - 1,
        Number(day),
        Number(hours ?? 0),
        Number(minutes ?? 0),
        Number(seconds ?? 0)
    ).getTime()
}
