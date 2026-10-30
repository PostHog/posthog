import { DateRange } from '~/queries/schema/schema-general'
import { isFunnelsQuery, isStickinessQuery, isTrendsQuery } from '~/queries/utils'

export type IsoDayOfWeek = NonNullable<DateRange['daysOfWeek']>[number]

/** Mirrors backend support: trends, stickiness, and funnels. Lifecycle is excluded because its
 *  statuses are defined by interval adjacency, which a sparse day axis breaks (weekend-only users
 *  get misclassified as resurrecting, dormant lands on excluded days). */
export function querySupportsDaysOfWeek(querySource: Record<string, any> | null | undefined): boolean {
    return isTrendsQuery(querySource) || isStickinessQuery(querySource) || isFunnelsQuery(querySource)
}

const DAYS_IN_WEEK = 7
const WEEKDAYS: IsoDayOfWeek[] = [1, 2, 3, 4, 5]
const WEEKENDS: IsoDayOfWeek[] = [6, 7]
const DAY_LABELS: Record<number, string> = {
    1: 'Mon',
    2: 'Tue',
    3: 'Wed',
    4: 'Thu',
    5: 'Fri',
    6: 'Sat',
    7: 'Sun',
}

export const ALL_DAY_NUMBERS: IsoDayOfWeek[] = [1, 2, 3, 4, 5, 6, 7]

function sortDays(days: IsoDayOfWeek[]): IsoDayOfWeek[] {
    return [...days].sort((a, b) => a - b)
}

/** [] means all days on both sides of the inversion. */
export function invertDaysOfWeek(days: IsoDayOfWeek[]): IsoDayOfWeek[] {
    return days.length === 0 ? [] : ALL_DAY_NUMBERS.filter((day) => !days.includes(day))
}

/** ISO days (1=Mon…7=Sun) the query filters OUT; [] means nothing is excluded. */
export function getExcludedDaysOfWeek(dateRange: DateRange | null | undefined): IsoDayOfWeek[] {
    return dateRange?.daysOfWeek?.length ? invertDaysOfWeek(sortDays(dateRange.daysOfWeek)) : []
}

/** Parses the day picker's string values, dropping anything outside 1-7 rather than casting. */
export function parseIsoDaysOfWeek(days: string[]): IsoDayOfWeek[] {
    return days
        .map((day) => parseInt(day, 10))
        .filter((day): day is IsoDayOfWeek => (ALL_DAY_NUMBERS as number[]).includes(day))
}

/** Order-insensitive equality, so re-picking the same days in a different order isn't a change. */
export function daysOfWeekSetsEqual(a: IsoDayOfWeek[], b: IsoDayOfWeek[]): boolean {
    if (a.length !== b.length) {
        return false
    }
    const sortedA = sortDays(a)
    const sortedB = sortDays(b)
    return sortedA.every((day, i) => day === sortedB[i])
}

export function daysOfWeekLabel(days: IsoDayOfWeek[]): string {
    if (days.length === 0 || days.length === DAYS_IN_WEEK) {
        return 'All days'
    }
    if (days.length === WEEKDAYS.length && WEEKDAYS.every((day) => days.includes(day))) {
        return 'Weekdays'
    }
    if (days.length === WEEKENDS.length && WEEKENDS.every((day) => days.includes(day))) {
        return 'Weekends'
    }
    return days.map((day) => DAY_LABELS[day]).join(', ')
}

/** 0 or 7 excluded days normalise to daysOfWeek: null ("all days included"). */
export function computeDaysOfWeekUpdate(
    excludedDays: IsoDayOfWeek[],
    dateRange: DateRange | null | undefined
): { dateRange: DateRange } {
    const included = invertDaysOfWeek(excludedDays)
    const daysOfWeek = included.length === 0 || included.length === DAYS_IN_WEEK ? null : sortDays(included)
    return { dateRange: { ...dateRange, daysOfWeek } }
}
