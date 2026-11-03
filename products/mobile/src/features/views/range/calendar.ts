// Calendar days are `YYYY-MM-DD` strings in the project timezone, the same strings a custom range sends. The math runs
// on UTC midnights, so the phone's own timezone never moves a day.

const DAY_MS = 86_400_000
const MONTHS = [
    'January',
    'February',
    'March',
    'April',
    'May',
    'June',
    'July',
    'August',
    'September',
    'October',
    'November',
    'December',
] as const
const WEEKDAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'] as const

function utc(day: string): Date {
    const [year, month, date] = day.split('-').map(Number)
    return new Date(Date.UTC(year ?? 1970, (month ?? 1) - 1, date ?? 1))
}

function dayString(date: Date): string {
    return date.toISOString().slice(0, 10)
}

export function monthOf(day: string): string {
    return `${day.slice(0, 7)}-01`
}

export function addMonths(month: string, count: number): string {
    const date = utc(month)
    return dayString(new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + count, 1)))
}

export interface MonthGrid {
    /** Empty cells before the 1st, for a week that starts on Sunday. */
    lead: number
    days: string[]
}

export function monthGrid(month: string): MonthGrid {
    const first = utc(month)
    const next = new Date(Date.UTC(first.getUTCFullYear(), first.getUTCMonth() + 1, 1))
    const count = Math.round((next.getTime() - first.getTime()) / DAY_MS)
    return {
        lead: first.getUTCDay(),
        days: Array.from({ length: count }, (_, index) => dayString(new Date(first.getTime() + index * DAY_MS))),
    }
}

/** "October 2026". */
export function monthTitle(month: string): string {
    const date = utc(month)
    return `${MONTHS[date.getUTCMonth()]} ${date.getUTCFullYear()}`
}

/** "Oct 5, 2026". */
export function dayTitle(day: string): string {
    const date = utc(day)
    return `${MONTHS[date.getUTCMonth()]?.slice(0, 3)} ${date.getUTCDate()}, ${date.getUTCFullYear()}`
}

/** "Monday, October 5, 2026", for screen readers. */
export function daySpoken(day: string): string {
    const date = utc(day)
    return `${WEEKDAYS[date.getUTCDay()]}, ${MONTHS[date.getUTCMonth()]} ${date.getUTCDate()}, ${date.getUTCFullYear()}`
}

export function daysInclusive(from: string, to: string): number {
    return Math.round((utc(to).getTime() - utc(from).getTime()) / DAY_MS) + 1
}

export interface CalendarPick {
    start: string | null
    end: string | null
}

/** The first tap sets the start and the second the end, swapped when it is earlier. A third tap starts over. */
export function pickDay(pick: CalendarPick, day: string): CalendarPick {
    if (!pick.start || pick.end) {
        return { start: day, end: null }
    }
    return pick.start <= day ? { start: pick.start, end: day } : { start: day, end: pick.start }
}
