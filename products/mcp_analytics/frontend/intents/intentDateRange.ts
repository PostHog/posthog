const HOURS_RELATIVE = /^-\d+h$/
const TIME_OF_DAY = /\d{1,2}:\d{2}/

/** Intent topics read daily rollups, so a bound with hour precision widens to the whole day it falls in. */
export function countsPartialDays(dateFrom: string | null, dateTo: string | null): boolean {
    return [dateFrom, dateTo].some((bound) => !!bound && (HOURS_RELATIVE.test(bound) || TIME_OF_DAY.test(bound)))
}
