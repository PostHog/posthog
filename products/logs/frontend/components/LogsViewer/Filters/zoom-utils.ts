import { dayjs } from 'lib/dayjs'
import { dateStringToDayJs } from 'lib/utils'

// PostHog relative date units: `M` = minute, `h` = hour, `d` = day, `w` = week,
// `m` = month, `q` = quarter, `y` = year (matches `isStringDateRegex` in lib/utils).
const RELATIVE_DATE_REGEX = /(^-?)(\d+)([Mhdwmqy])$/

// Step a unit down to a smaller unit when a zoom-in would otherwise produce a
// fractional or zero amount (e.g. `-1h` * 0.5 collapsing to a no-op).
const RELATIVE_UNIT_STEP_DOWN: Record<string, { unit: string; perUnit: number }> = {
    y: { unit: 'm', perUnit: 12 },
    q: { unit: 'm', perUnit: 3 },
    m: { unit: 'd', perUnit: 30 },
    w: { unit: 'd', perUnit: 7 },
    d: { unit: 'h', perUnit: 24 },
    h: { unit: 'M', perUnit: 60 },
}

const zoomDateRelative = (date: string | null | undefined, multiplier: number): string | null => {
    if (!date) {
        return null
    }
    const match = date.match(RELATIVE_DATE_REGEX)
    if (!match) {
        return null
    }

    const [, sign, amountStr, unit] = match
    let amount = parseInt(amountStr)
    let currentUnit = unit
    let scaled = amount * multiplier

    // When zooming in collapses the amount below 1 in the current unit, drop to
    // a smaller unit so the visible range still changes meaningfully.
    while (scaled < 1 && RELATIVE_UNIT_STEP_DOWN[currentUnit]) {
        const stepDown = RELATIVE_UNIT_STEP_DOWN[currentUnit]
        amount = amount * stepDown.perUnit
        currentUnit = stepDown.unit
        scaled = amount * multiplier
    }

    // Round to ensure we always move (e.g. 1.5 → 2 when zooming out, 1.5 → 2 when zooming in)
    // and clamp to a minimum of 1 so the range never becomes a zero-duration no-op.
    const newAmount = Math.max(1, Math.round(scaled))
    return `${sign}${newAmount}${currentUnit}`
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
