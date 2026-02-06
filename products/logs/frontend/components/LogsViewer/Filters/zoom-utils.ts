import { dayjs } from 'lib/dayjs'
import { dateStringToDayJs } from 'lib/utils'

const RELATIVE_DATE_REGEX = /(^-?)(\d+)([hdwmy])$/

const zoomDateRelative = (date: string | null | undefined, multiplier: number): string | null => {
    if (!date) {
        return null
    }
    const match = date.match(RELATIVE_DATE_REGEX)
    if (match) {
        // Just multiply the value if we have it
        const [, sign, amount, unit] = match
        const newAmount = parseInt(amount) * multiplier
        return `${sign}${newAmount}${unit}`
    }
    return null
}

export const zoomDateRange = (
    dateRange: { date_from?: string | null; date_to?: string | null },
    multiplier: number
): { date_from?: string | null; date_to?: string | null } => {
    const now = dayjs()
    // If only date_from is set and is relative we can do a nicer zoom function
    if (dateRange.date_from && !dateRange.date_to) {
        const newDateFrom = zoomDateRelative(dateRange.date_from, multiplier)
        if (newDateFrom) {
            return {
                date_from: newDateFrom,
                date_to: null,
            }
        }
    }

    const start = dateRange.date_from
        ? (dateStringToDayJs(dateRange.date_from) ?? now.subtract(1, 'hour'))
        : now.subtract(1, 'hour')
    const end = dateRange.date_to ? (dateStringToDayJs(dateRange.date_to) ?? now) : now

    // Use a minimum of 1 minute when diff is 0 (same from/to timestamps) to allow zooming out
    const diffMins = Math.max(end.diff(start, 'minutes'), 1)
    const centerDate = start.add(diffMins * 0.5, 'minutes')

    const newStart = centerDate.subtract(diffMins * 0.5 * multiplier, 'minutes')
    const newEnd = centerDate.add(diffMins * 0.5 * multiplier, 'minutes')

    return {
        date_from: newStart.format('YYYY-MM-DDTHH:mm:ss.SSSZ'),
        date_to: (newEnd.isAfter(now) ? now : newEnd).format('YYYY-MM-DDTHH:mm:ss.SSSZ'),
    }
}
