// Written by hand instead of with Intl so the output is identical in Hermes, the web build and Jest.

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'] as const
const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'] as const

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
