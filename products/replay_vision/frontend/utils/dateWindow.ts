import { dayjs } from 'lib/dayjs'
import { dateStringToDayJs } from 'lib/utils/dateFilters'

/** Convert a DateFilter token (`-30d`, an ISO date, or null) into an ISO instant for the API. */
export function resolveWindowBound(value: string | null, fallback: dayjs.Dayjs): string {
    return ((value && dateStringToDayJs(value)) || fallback).toISOString()
}
